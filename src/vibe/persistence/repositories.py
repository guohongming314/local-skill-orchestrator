from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker

from vibe.persistence.models import CodexThread, Run


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset({RunStatus.PAUSED, RunStatus.COMPLETED, RunStatus.FAILED}),
    RunStatus.PAUSED: frozenset({RunStatus.RUNNING, RunStatus.FAILED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
}


class InvalidRunTransition(ValueError):
    """Raised when a run lifecycle transition is not allowed."""


@dataclass(frozen=True)
class RunRecord:
    graph_run_id: str
    status: RunStatus
    repository_digest: str
    checkpoint_namespace: str | None
    resume_input_digest: str | None
    permission_state_digest: str | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CodexThreadRecord:
    graph_run_id: str
    codex_thread_id: str
    created_at: datetime
    updated_at: datetime


def _run_record(model: Run) -> RunRecord:
    return RunRecord(
        graph_run_id=model.id,
        status=RunStatus(model.status),
        repository_digest=model.repository_digest,
        checkpoint_namespace=model.checkpoint_namespace,
        resume_input_digest=model.resume_input_digest,
        permission_state_digest=model.permission_state_digest,
        error_summary=model.error_summary,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _thread_record(model: CodexThread) -> CodexThreadRecord:
    return CodexThreadRecord(
        graph_run_id=model.run_id,
        codex_thread_id=model.codex_thread_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class RunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        *,
        graph_run_id: str,
        repository_digest: str,
        checkpoint_namespace: str | None = None,
        resume_input_digest: str | None = None,
        permission_state_digest: str | None = None,
    ) -> RunRecord:
        with self._session_factory.begin() as session:
            run = Run(
                id=graph_run_id,
                status=RunStatus.PENDING.value,
                repository_digest=repository_digest,
                checkpoint_namespace=checkpoint_namespace,
                resume_input_digest=resume_input_digest,
                permission_state_digest=permission_state_digest,
            )
            session.add(run)
            session.flush()
            session.refresh(run)
            return _run_record(run)

    def get(self, graph_run_id: str) -> RunRecord:
        with self._session_factory() as session:
            run = session.get(Run, graph_run_id)
            if run is None:
                raise LookupError(f"run {graph_run_id!r} does not exist")
            return _run_record(run)

    def transition(
        self,
        graph_run_id: str,
        new_status: RunStatus,
        *,
        error_summary: str | None = None,
    ) -> RunRecord:
        with self._session_factory.begin() as session:
            run = session.get(Run, graph_run_id)
            if run is None:
                raise LookupError(f"run {graph_run_id!r} does not exist")
            current_status = RunStatus(run.status)
            if new_status not in _ALLOWED_TRANSITIONS[current_status]:
                raise InvalidRunTransition(
                    f"cannot transition run {graph_run_id!r} from "
                    f"{current_status.value} to {new_status.value}"
                )
            if error_summary is not None and new_status is not RunStatus.FAILED:
                raise ValueError("error_summary is only valid for failed runs")
            run.status = new_status.value
            run.error_summary = error_summary
            session.flush()
            session.refresh(run)
            return _run_record(run)


class CodexThreadRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def associate(self, graph_run_id: str, codex_thread_id: str) -> CodexThreadRecord:
        with self._session_factory.begin() as session:
            if session.get(Run, graph_run_id) is None:
                raise LookupError(f"run {graph_run_id!r} does not exist")
            thread = CodexThread(run_id=graph_run_id, codex_thread_id=codex_thread_id)
            session.add(thread)
            session.flush()
            session.refresh(thread)
            return _thread_record(thread)

    def get_by_run_id(self, graph_run_id: str) -> CodexThreadRecord | None:
        return self._find(CodexThread.run_id, graph_run_id)

    def get_by_thread_id(self, codex_thread_id: str) -> CodexThreadRecord | None:
        return self._find(CodexThread.codex_thread_id, codex_thread_id)

    def _find(self, field: InstrumentedAttribute[str], value: str) -> CodexThreadRecord | None:
        with self._session_factory() as session:
            thread = session.scalar(select(CodexThread).where(field == value))
            return None if thread is None else _thread_record(thread)