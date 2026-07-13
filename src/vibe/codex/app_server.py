"""High-level Codex app-server thread and turn lifecycle adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import anyio

from vibe.codex.events import CodexEvent, CodexEventKind, TurnStatus
from vibe.codex.jsonrpc import JsonRpcSubprocessClient
from vibe.codex.protocol import JsonObject, JsonRpcNotification, JsonValue


class CodexProtocolError(RuntimeError):
    """The app-server returned a response that violates the expected lifecycle contract."""


class CodexTurnTimeoutError(TimeoutError):
    """A turn exceeded its deadline and was interrupted cleanly."""

    def __init__(self, turn_id: str, timeout: float) -> None:
        self.turn_id = turn_id
        self.timeout = timeout
        super().__init__(f"Codex turn {turn_id!r} timed out after {timeout:g} seconds")


@dataclass(frozen=True, slots=True)
class CodexServerInfo:
    user_agent: str
    codex_home: Path
    platform_family: str
    platform_os: str


@dataclass(frozen=True, slots=True)
class CodexThread:
    id: str


@dataclass(frozen=True, slots=True)
class CodexTurn:
    id: str
    thread_id: str
    status: TurnStatus


@dataclass(frozen=True, slots=True)
class CodexTurnResult:
    turn: CodexTurn
    events: tuple[CodexEvent, ...]


class CodexAppServerClient:
    """Expose initialized thread and turn operations over a JSON-RPC transport."""

    def __init__(
        self,
        transport: JsonRpcSubprocessClient,
        *,
        client_name: str = "local-skill-orchestrator",
        client_version: str = "0.1.0",
    ) -> None:
        self._transport = transport
        self._client_name = client_name
        self._client_version = client_version
        self._initialized = False

    async def initialize(self) -> CodexServerInfo:
        """Perform the required initialize request and initialized notification handshake."""
        if self._initialized:
            raise RuntimeError("Codex app-server client is already initialized")
        result = _expect_object(
            await self._transport.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": self._client_name,
                        "version": self._client_version,
                    }
                },
            ),
            "initialize result",
        )
        info = CodexServerInfo(
            user_agent=_expect_string(result, "userAgent"),
            codex_home=Path(_expect_string(result, "codexHome")),
            platform_family=_expect_string(result, "platformFamily"),
            platform_os=_expect_string(result, "platformOs"),
        )
        await self._transport.notify("initialized")
        self._initialized = True
        return info

    async def start_thread(self, *, cwd: str | Path | None = None) -> CodexThread:
        """Create a new app-server thread."""
        self._ensure_initialized()
        params: JsonObject = {}
        if cwd is not None:
            params["cwd"] = str(Path(cwd).resolve())
        result = _expect_object(
            await self._transport.request("thread/start", params), "thread/start result"
        )
        return _parse_thread(result)

    async def resume_thread(self, thread_id: str) -> CodexThread:
        """Resume a persisted app-server thread by its stable Codex thread id."""
        self._ensure_initialized()
        result = _expect_object(
            await self._transport.request("thread/resume", {"threadId": thread_id}),
            "thread/resume result",
        )
        return _parse_thread(result)

    async def start_turn(self, thread_id: str, text: str) -> CodexTurn:
        """Start a text turn on an existing thread."""
        self._ensure_initialized()
        result = _expect_object(
            await self._transport.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": text}],
                },
            ),
            "turn/start result",
        )
        turn = _expect_object(result.get("turn"), "turn/start turn")
        return _parse_turn(turn, thread_id)

    async def stream_events(self, turn: CodexTurn) -> AsyncIterator[CodexEvent]:
        """Stream normalized events for one turn until its terminal notification."""
        while True:
            notification = await self._transport.receive_notification()
            event = _normalize_event(notification)
            if event.thread_id != turn.thread_id or event.turn_id != turn.id:
                continue
            yield event
            if event.kind is CodexEventKind.TURN_COMPLETED:
                return

    async def run_turn(
        self,
        thread_id: str,
        text: str,
        *,
        timeout: float = 300.0,
    ) -> CodexTurnResult:
        """Run a turn to completion, interrupting it before reporting a timeout."""
        turn = await self.start_turn(thread_id, text)
        events: list[CodexEvent] = []
        try:
            with anyio.fail_after(timeout):
                async for event in self.stream_events(turn):
                    events.append(event)
        except TimeoutError as exc:
            with anyio.CancelScope(shield=True):
                await self.cancel_turn(turn)
                with anyio.move_on_after(2):
                    async for _event in self.stream_events(turn):
                        pass
            raise CodexTurnTimeoutError(turn.id, timeout) from exc
        completed = events[-1]
        status = completed.status
        if status is None:
            raise CodexProtocolError("turn/completed event did not include a status")
        return CodexTurnResult(
            turn=CodexTurn(id=turn.id, thread_id=turn.thread_id, status=status),
            events=tuple(events),
        )

    async def cancel_turn(self, turn: CodexTurn) -> None:
        """Interrupt an active turn; completion remains available on the event stream."""
        self._ensure_initialized()
        await self._transport.request(
            "turn/interrupt", {"threadId": turn.thread_id, "turnId": turn.id}
        )

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("initialize() must be called before lifecycle operations")


def _parse_thread(result: JsonObject) -> CodexThread:
    thread = _expect_object(result.get("thread"), "thread response")
    return CodexThread(id=_expect_string(thread, "id"))


def _parse_turn(turn: JsonObject, thread_id: str) -> CodexTurn:
    return CodexTurn(
        id=_expect_string(turn, "id"),
        thread_id=thread_id,
        status=_parse_status(turn.get("status")),
    )


def _normalize_event(notification: JsonRpcNotification) -> CodexEvent:
    params = _expect_object(notification.params, f"{notification.method} params")
    kind = {
        "turn/started": CodexEventKind.TURN_STARTED,
        "item/started": CodexEventKind.ITEM_STARTED,
        "item/completed": CodexEventKind.ITEM_COMPLETED,
        "turn/completed": CodexEventKind.TURN_COMPLETED,
    }.get(notification.method, CodexEventKind.OTHER)
    thread_id = _optional_string(params.get("threadId"), "threadId")
    turn_value = params.get("turn")
    turn = _expect_object(turn_value, "turn event") if turn_value is not None else None
    turn_id = (
        _expect_string(turn, "id")
        if turn is not None
        else _optional_string(params.get("turnId"), "turnId")
    )
    status = _parse_status(turn.get("status")) if turn is not None else None
    item_value = params.get("item")
    item = _expect_object(item_value, "item event") if item_value is not None else None
    return CodexEvent(kind, notification.method, thread_id, turn_id, status, item, params)


def _parse_status(value: JsonValue | None) -> TurnStatus:
    if not isinstance(value, str):
        raise CodexProtocolError("turn status must be a string")
    try:
        return TurnStatus(value)
    except ValueError as exc:
        raise CodexProtocolError(f"unknown turn status: {value!r}") from exc


def _expect_object(value: JsonValue | None, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise CodexProtocolError(f"{label} must be an object")
    return value


def _expect_string(value: JsonObject, key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise CodexProtocolError(f"{key} must be a string")
    return item


def _optional_string(value: JsonValue | None, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CodexProtocolError(f"{label} must be a string")
    return value
