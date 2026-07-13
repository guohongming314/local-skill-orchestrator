"""Validated state machine for resumable project initialization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from vibe.workflows.checkpoints import SqliteCheckpointStore
from vibe.workflows.state import InitCheckpoint, InitStage, InitStatus


class InvalidTransition(ValueError):
    """Raised before mutation when a workflow transition is invalid."""


_NEXT_STAGE = {
    current: following
    for current, following in zip(tuple(InitStage), tuple(InitStage)[1:], strict=False)
}
_TERMINAL = {InitStatus.CANCELLED, InitStatus.COMPLETED}


class InitializationGraph:
    """Advance a durable initialization graph through explicit safe transitions."""

    def __init__(self, checkpoints: SqliteCheckpointStore) -> None:
        self._checkpoints = checkpoints

    def start(self, run_id: str, *, repository_digest: str) -> InitCheckpoint:
        checkpoint = InitCheckpoint(
            checkpoint_id=f"init:{run_id}:{uuid4().hex}",
            run_id=run_id,
            repository_digest=repository_digest,
            stage=InitStage.INSPECT,
            status=InitStatus.RUNNING,
        )
        self._checkpoints.create(checkpoint)
        return checkpoint

    def load(self, run_id: str) -> InitCheckpoint:
        return self._checkpoints.load(run_id)

    def advance(
        self,
        run_id: str,
        stage: InitStage,
        *,
        confirmed: Mapping[str, Any] | None = None,
        side_effect: Callable[[], object] | None = None,
    ) -> InitCheckpoint:
        previous = self.load(run_id)
        self._require_status(previous, InitStatus.RUNNING)
        expected = _NEXT_STAGE.get(previous.stage)
        if stage is not expected:
            raise InvalidTransition(
                f"invalid initialization transition: {previous.stage.value} -> {stage.value}"
            )
        if side_effect is not None:
            side_effect()
        current = replace(
            previous,
            stage=stage,
            confirmed=self._merge(previous, confirmed),
            revision=previous.revision + 1,
        )
        return self._replace(previous, current)

    def revise(
        self,
        run_id: str,
        *,
        confirmed: Mapping[str, Any],
    ) -> InitCheckpoint:
        """Persist reviewed values without advancing the current stage."""
        previous = self.load(run_id)
        self._require_status(previous, InitStatus.RUNNING)
        current = replace(
            previous,
            confirmed=self._merge(previous, confirmed),
            revision=previous.revision + 1,
        )
        return self._replace(previous, current)
    def pause(self, run_id: str) -> InitCheckpoint:
        previous = self.load(run_id)
        self._require_status(previous, InitStatus.RUNNING)
        current = replace(
            previous, status=InitStatus.PAUSED, revision=previous.revision + 1
        )
        return self._replace(previous, current)

    def resume(self, run_id: str, *, repository_digest: str) -> InitCheckpoint:
        previous = self.load(run_id)
        self._require_status(previous, InitStatus.PAUSED)
        if repository_digest != previous.repository_digest:
            raise InvalidTransition("repository digest changed; direct resume rejected")
        current = replace(
            previous, status=InitStatus.RUNNING, revision=previous.revision + 1
        )
        return self._replace(previous, current)

    def fail(self, run_id: str, error: str) -> InitCheckpoint:
        previous = self.load(run_id)
        self._require_status(previous, InitStatus.RUNNING)
        current = replace(
            previous,
            status=InitStatus.FAILED,
            error=error,
            revision=previous.revision + 1,
        )
        return self._replace(previous, current)

    def retry(self, run_id: str) -> InitCheckpoint:
        previous = self.load(run_id)
        self._require_status(previous, InitStatus.FAILED)
        current = replace(
            previous,
            status=InitStatus.RUNNING,
            attempt=previous.attempt + 1,
            error=None,
            revision=previous.revision + 1,
        )
        return self._replace(previous, current)

    def cancel(self, run_id: str, *, reason: str) -> InitCheckpoint:
        previous = self.load(run_id)
        if previous.status in _TERMINAL:
            self._reject_status(previous)
        current = replace(
            previous,
            status=InitStatus.CANCELLED,
            cancellation_reason=reason,
            revision=previous.revision + 1,
        )
        return self._replace(previous, current)

    def complete(
        self, run_id: str, *, confirmed: Mapping[str, Any] | None = None
    ) -> InitCheckpoint:
        previous = self.load(run_id)
        self._require_status(previous, InitStatus.RUNNING)
        if previous.stage is not InitStage.VERIFY:
            raise InvalidTransition(
                f"cannot complete initialization from {previous.stage.value}"
            )
        current = replace(
            previous,
            status=InitStatus.COMPLETED,
            confirmed=self._merge(previous, confirmed),
            revision=previous.revision + 1,
        )
        return self._replace(previous, current)

    def _replace(
        self, previous: InitCheckpoint, current: InitCheckpoint
    ) -> InitCheckpoint:
        self._checkpoints.replace(previous, current)
        return current

    @staticmethod
    def _merge(
        previous: InitCheckpoint, confirmed: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        merged = dict(previous.confirmed)
        if confirmed is not None:
            merged.update(confirmed)
        return merged

    @classmethod
    def _require_status(cls, checkpoint: InitCheckpoint, expected: InitStatus) -> None:
        if checkpoint.status is not expected:
            cls._reject_status(checkpoint)

    @staticmethod
    def _reject_status(checkpoint: InitCheckpoint) -> None:
        raise InvalidTransition(
            f"run {checkpoint.run_id!r} is {checkpoint.status.value}; transition rejected"
        )
