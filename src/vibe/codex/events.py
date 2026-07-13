"""Project-owned normalized Codex app-server event types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vibe.codex.protocol import JsonObject


class CodexEventKind(StrEnum):
    TURN_STARTED = "turn_started"
    ITEM_STARTED = "item_started"
    ITEM_COMPLETED = "item_completed"
    TURN_COMPLETED = "turn_completed"
    OTHER = "other"


class TurnStatus(StrEnum):
    IN_PROGRESS = "inProgress"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CodexEvent:
    kind: CodexEventKind
    method: str
    thread_id: str | None
    turn_id: str | None
    status: TurnStatus | None
    item: JsonObject | None
    payload: JsonObject
