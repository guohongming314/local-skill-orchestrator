"""Newline-delimited JSON-RPC transport over a managed subprocess."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import cast

import anyio
from anyio.abc import ByteReceiveStream, ByteSendStream, Process, TaskGroup

from vibe.codex.protocol import (
    JsonObject,
    JsonRpcEOFError,
    JsonRpcId,
    JsonRpcMalformedMessageError,
    JsonRpcNotification,
    JsonRpcProcessError,
    JsonRpcRemoteError,
    JsonRpcServerRequest,
    JsonRpcTimeoutError,
    JsonRpcTransportError,
    JsonValue,
)


@dataclass(slots=True)
class _PendingRequest:
    event: anyio.Event
    result: JsonValue | None = None
    error: JsonRpcTransportError | None = None


class JsonRpcSubprocessClient:
    """Manage a JSONL JSON-RPC subprocess and correlate bidirectional messages."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("command must not be empty")
        self._command = tuple(command)
        self._env = dict(env) if env is not None else _minimal_environment()
        self._process: Process | None = None
        self._task_group: TaskGroup | None = None
        self._pending: dict[JsonRpcId, _PendingRequest] = {}
        self._next_id = 1
        self._write_lock = anyio.Lock()
        self._notifications_send, self._notifications_receive = anyio.create_memory_object_stream[
            JsonRpcNotification
        ](100)
        server_request_streams = anyio.create_memory_object_stream[JsonRpcServerRequest](100)
        self._server_requests_send, self._server_requests_receive = server_request_streams
        self._stderr_parts: list[bytes] = []
        self._stderr_complete = anyio.Event()
        self._terminal_error: JsonRpcTransportError | None = None
        self._closing = False

    @property
    def pid(self) -> int | None:
        """Return the managed process id after startup."""
        return self._process.pid if self._process is not None else None

    @property
    def returncode(self) -> int | None:
        """Return the subprocess status once it has exited."""
        return self._process.returncode if self._process is not None else None

    async def __aenter__(self) -> JsonRpcSubprocessClient:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def start(self) -> None:
        """Start the subprocess and background routing tasks."""
        if self._process is not None:
            raise RuntimeError("JSON-RPC client has already been started")
        self._process = await anyio.open_process(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env,
        )
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._read_stdout)
        self._task_group.start_soon(self._read_stderr)

    async def request(
        self,
        method: str,
        params: JsonValue | None = None,
        *,
        timeout: float = 30.0,
    ) -> JsonValue | None:
        """Send a request and wait for the response with the matching id."""
        self._ensure_usable()
        request_id = self._next_id
        self._next_id += 1
        pending = _PendingRequest(event=anyio.Event())
        self._pending[request_id] = pending
        message: JsonObject = {"id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            await self._send(message)
            try:
                with anyio.fail_after(timeout):
                    await pending.event.wait()
            except TimeoutError as exc:
                raise JsonRpcTimeoutError(method, timeout) from exc
            if pending.error is not None:
                raise pending.error
            return pending.result
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: JsonValue | None = None) -> None:
        """Send a client-to-server notification."""
        self._ensure_usable()
        message: JsonObject = {"method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)

    async def receive_notification(self) -> JsonRpcNotification:
        """Wait for the next server notification."""
        return await self._notifications_receive.receive()

    async def receive_server_request(self) -> JsonRpcServerRequest:
        """Wait for the next server-to-client request."""
        return await self._server_requests_receive.receive()

    async def respond(
        self,
        request_id: JsonRpcId,
        result: JsonValue | None = None,
        *,
        error: JsonRpcRemoteError | None = None,
    ) -> None:
        """Respond to a server-to-client request."""
        if error is not None and result is not None:
            raise ValueError("a response cannot contain both result and error")
        message: JsonObject = {"id": request_id}
        if error is None:
            message["result"] = result
        else:
            error_payload: JsonObject = {"code": error.code, "message": error.message}
            if error.data is not None:
                error_payload["data"] = error.data
            message["error"] = error_payload
        await self._send(message)

    async def close(self) -> None:
        """Stop and reap the subprocess, leaving no child process behind."""
        process = self._process
        task_group = self._task_group
        if process is None or task_group is None:
            return
        self._closing = True
        if process.stdin is not None:
            await process.stdin.aclose()
        if process.returncode is None:
            with anyio.move_on_after(0.5):
                await process.wait()
        if process.returncode is None:
            process.terminate()
            with anyio.move_on_after(1):
                await process.wait()
        if process.returncode is None:
            process.kill()
            await process.wait()
        task_group.cancel_scope.cancel()
        await task_group.__aexit__(None, None, None)
        await self._notifications_send.aclose()
        await self._server_requests_send.aclose()

    def _ensure_usable(self) -> None:
        if self._process is None:
            raise RuntimeError("JSON-RPC client has not been started")
        if self._terminal_error is not None:
            raise self._terminal_error
        if self._closing:
            raise JsonRpcEOFError("app-server transport is closing")

    async def _send(self, message: JsonObject) -> None:
        self._ensure_usable()
        process = cast(Process, self._process)
        stdin = cast(ByteSendStream, process.stdin)
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
        async with self._write_lock:
            try:
                await stdin.send(payload)
            except (anyio.BrokenResourceError, anyio.ClosedResourceError) as exc:
                error = await self._exit_error_or_eof()
                self._fail(error)
                raise error from exc

    async def _read_stdout(self) -> None:
        process = cast(Process, self._process)
        stdout = cast(ByteReceiveStream, process.stdout)
        buffer = bytearray()
        try:
            while True:
                chunk = await stdout.receive(65536)
                buffer.extend(chunk)
                while b"\n" in buffer:
                    raw_line, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    if raw_line.strip():
                        await self._route_line(bytes(raw_line))
        except anyio.EndOfStream:
            if buffer.strip():
                await self._route_line(bytes(buffer))
            if not self._closing:
                self._fail(await self._exit_error_or_eof())
        except JsonRpcTransportError as error:
            self._fail(error)

    async def _read_stderr(self) -> None:
        process = cast(Process, self._process)
        stderr = cast(ByteReceiveStream, process.stderr)
        try:
            while True:
                self._stderr_parts.append(await stderr.receive(65536))
        except anyio.EndOfStream:
            pass
        finally:
            self._stderr_complete.set()

    async def _route_line(self, raw_line: bytes) -> None:
        try:
            decoded = raw_line.decode("utf-8")
            value = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            preview = raw_line[:200].decode("utf-8", errors="replace")
            raise JsonRpcMalformedMessageError(
                f"app-server output is not valid JSON: {preview!r}"
            ) from exc
        if not isinstance(value, dict):
            raise JsonRpcMalformedMessageError("app-server JSON-RPC message must be an object")
        message = cast(dict[str, object], value)
        if "method" in message:
            await self._route_server_message(message)
            return
        if "id" in message:
            self._route_response(message)
            return
        raise JsonRpcMalformedMessageError("app-server message has neither method nor id")

    async def _route_server_message(self, message: dict[str, object]) -> None:
        method = message.get("method")
        if not isinstance(method, str):
            raise JsonRpcMalformedMessageError("JSON-RPC method must be a string")
        params = _as_json_value(message.get("params"))
        if "id" not in message:
            await self._notifications_send.send(JsonRpcNotification(method, params))
            return
        request_id = _as_request_id(message["id"])
        await self._server_requests_send.send(JsonRpcServerRequest(request_id, method, params))

    def _route_response(self, message: dict[str, object]) -> None:
        request_id = _as_request_id(message["id"])
        pending = self._pending.get(request_id)
        if pending is None:
            return
        if "error" in message:
            pending.error = _parse_remote_error(message["error"])
        elif "result" in message:
            pending.result = _as_json_value(message["result"])
        else:
            pending.error = JsonRpcMalformedMessageError(
                f"response {request_id!r} has neither result nor error"
            )
        pending.event.set()

    async def _exit_error_or_eof(self) -> JsonRpcTransportError:
        process = cast(Process, self._process)
        returncode = await process.wait()
        with anyio.move_on_after(1):
            await self._stderr_complete.wait()
        stderr = b"".join(self._stderr_parts).decode("utf-8", errors="replace")
        if returncode != 0:
            return JsonRpcProcessError(returncode, stderr)
        return JsonRpcEOFError("app-server stdout closed before a response was received")

    def _fail(self, error: JsonRpcTransportError) -> None:
        if self._terminal_error is not None:
            return
        self._terminal_error = error
        for pending in self._pending.values():
            pending.error = error
            pending.event.set()


def _minimal_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "CODEX_HOME",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "LOG_FORMAT",
        "PATH",
        "RUST_LOG",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
    }
    return {name: value for name, value in os.environ.items() if name.upper() in allowed}


def _as_request_id(value: object) -> JsonRpcId:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise JsonRpcMalformedMessageError("JSON-RPC id must be an integer or string")
    return value


def _as_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_as_json_value(item) for item in value]
    if isinstance(value, dict):
        converted: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise JsonRpcMalformedMessageError("JSON object keys must be strings")
            converted[key] = _as_json_value(item)
        return converted
    raise JsonRpcMalformedMessageError(f"unsupported JSON value: {type(value).__name__}")


def _parse_remote_error(value: object) -> JsonRpcRemoteError:
    if not isinstance(value, dict):
        raise JsonRpcMalformedMessageError("JSON-RPC error must be an object")
    code = value.get("code")
    message = value.get("message")
    if isinstance(code, bool) or not isinstance(code, int) or not isinstance(message, str):
        raise JsonRpcMalformedMessageError(
            "JSON-RPC error requires integer code and string message"
        )
    data = _as_json_value(value.get("data")) if "data" in value else None
    return JsonRpcRemoteError(code, message, data)
