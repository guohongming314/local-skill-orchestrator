"""Typed state for the resumable project-initialization workflow."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class InitStage(StrEnum):
    """Ordered initialization stages."""

    INSPECT = "inspect"
    INVENTORY = "inventory"
    INTERVIEW = "interview"
    MODEL = "model"
    RESOLVE = "resolve"
    REVIEW = "review"
    APPLY = "apply"
    VERIFY = "verify"


class InitStatus(StrEnum):
    """Lifecycle status for an initialization run."""

    RUNNING = "running"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass(frozen=True)
class InitCheckpoint:
    """Durable, immutable snapshot of one initialization run."""

    checkpoint_id: str
    run_id: str
    repository_digest: str
    stage: InitStage
    status: InitStatus
    confirmed: Mapping[str, Any] = field(default_factory=dict)
    attempt: int = 1
    revision: int = 1
    error: str | None = None
    cancellation_reason: str | None = None
