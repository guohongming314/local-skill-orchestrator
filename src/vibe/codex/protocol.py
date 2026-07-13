"""Typed JSON-RPC protocol values and transport errors."""

from __future__ import annotations

from dataclasses import dataclass

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type JsonRpcId = int | str


@dataclass(frozen=True, slots=True)
class JsonRpcNotification:
    """A server-to-client notification without a request id."""

    method: str
    params: JsonValue | None = None


@dataclass(frozen=True, slots=True)
class JsonRpcServerRequest:
    """A server-to-client request that requires a correlated response."""

    id: JsonRpcId
    method: str
    params: JsonValue | None = None


class JsonRpcTransportError(RuntimeError):
    """Base class for local JSON-RPC transport failures."""


class JsonRpcEOFError(JsonRpcTransportError):
    """The subprocess closed stdout before completing pending work."""


class JsonRpcMalformedMessageError(JsonRpcTransportError):
    """The subprocess emitted a line that is not a valid JSON-RPC message."""


class JsonRpcTimeoutError(JsonRpcTransportError):
    """A request did not complete within its deadline."""

    def __init__(self, method: str, timeout: float) -> None:
        self.method = method
        self.timeout = timeout
        super().__init__(f"JSON-RPC request {method!r} timed out after {timeout:g} seconds")


class JsonRpcProcessError(JsonRpcTransportError):
    """The managed subprocess exited unsuccessfully."""

    def __init__(self, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr
        detail = stderr.strip() or "no stderr output"
        super().__init__(f"app-server exited with status {returncode}: {detail}")


class JsonRpcRemoteError(JsonRpcTransportError):
    """A JSON-RPC error response returned by the remote server."""

    def __init__(self, code: int, message: str, data: JsonValue | None = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"JSON-RPC error {code}: {message}")
