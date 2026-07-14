from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker

from vibe.models.outcome import TaskOutcome
from vibe.persistence.models import (
    AuditEvent,
    CapabilityVerification,
    CodexThread,
    InventoryCache,
    Run,
    TaskOutcomeRow,
    UserTrustDecision,
)


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


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_SECRET_KEY_TERMS = ("secret", "password", "credential", "api_key", "private_key")


class SecretLikePayloadError(ValueError):
    """Raised before a payload with a secret-like field can reach persistence."""


def _reject_secret_like_fields(value: JsonValue, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = key.lower().replace("-", "_").replace(" ", "_")
            is_secret = any(term in normalized for term in _SECRET_KEY_TERMS)
            is_token = normalized == "token" or normalized.endswith("_token")
            if is_secret or is_token:
                location = ".".join((*path, key))
                raise SecretLikePayloadError(f"secret-like field {location!r} is not allowed")
            _reject_secret_like_fields(nested, (*path, key))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_like_fields(nested, (*path, str(index)))


def _comparable_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _payload(value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    payload = dict(value)
    _reject_secret_like_fields(payload)
    return payload


def _encode(value: Mapping[str, JsonValue]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _decode(value: str) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], json.loads(value))


@dataclass(frozen=True)
class InventoryCacheRecord:
    source_digest: str
    scope: tuple[str, ...]
    snapshot: dict[str, JsonValue]
    created_at: datetime
    expires_at: datetime | None


class InventoryCacheRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def put(
        self,
        *,
        source_digest: str,
        scope: Sequence[str],
        snapshot: Mapping[str, JsonValue],
        expires_at: datetime | None = None,
    ) -> InventoryCacheRecord:
        safe_snapshot = _payload(snapshot)
        envelope: dict[str, JsonValue] = {
            "scope": list(scope),
            "snapshot": safe_snapshot,
        }
        with self._session_factory.begin() as session:
            model = session.scalar(
                select(InventoryCache).where(InventoryCache.source_digest == source_digest)
            )
            if model is None:
                model = InventoryCache(
                    source_digest=source_digest,
                    inventory_json=_encode(envelope),
                    expires_at=expires_at,
                )
                session.add(model)
            else:
                model.inventory_json = _encode(envelope)
                model.expires_at = expires_at
            session.flush()
            session.refresh(model)
            return self._record(model)

    def get(
        self,
        source_digest: str,
        scope: Sequence[str],
        *,
        as_of: datetime | None = None,
    ) -> InventoryCacheRecord | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(InventoryCache).where(InventoryCache.source_digest == source_digest)
            )
            if model is None:
                return None
            record = self._record(model)
            if record.scope != tuple(scope):
                return None
            checked_at = as_of or datetime.now(UTC)
            if record.expires_at is not None and _comparable_time(
                record.expires_at
            ) <= _comparable_time(checked_at):
                return None
            return record

    @staticmethod
    def _record(model: InventoryCache) -> InventoryCacheRecord:
        envelope = _decode(model.inventory_json)
        return InventoryCacheRecord(
            source_digest=model.source_digest,
            scope=tuple(cast(list[str], envelope["scope"])),
            snapshot=cast(dict[str, JsonValue], envelope["snapshot"]),
            created_at=model.created_at,
            expires_at=model.expires_at,
        )


@dataclass(frozen=True)
class CapabilityVerificationRecord:
    capability_id: str
    content_digest: str
    scope: tuple[str, ...]
    status: str
    reason: str
    details: dict[str, JsonValue]
    verified_at: datetime


class CapabilityVerificationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        *,
        capability_id: str,
        content_digest: str,
        scope: Sequence[str],
        status: str,
        reason: str,
        details: Mapping[str, JsonValue],
    ) -> CapabilityVerificationRecord:
        envelope: dict[str, JsonValue] = {
            "scope": list(scope),
            "reason": reason,
            "details": _payload(details),
        }
        with self._session_factory.begin() as session:
            model = session.scalar(
                select(CapabilityVerification).where(
                    CapabilityVerification.capability_id == capability_id,
                    CapabilityVerification.content_digest == content_digest,
                )
            )
            if model is None:
                model = CapabilityVerification(
                    capability_id=capability_id,
                    content_digest=content_digest,
                    status=status,
                    details_json=_encode(envelope),
                )
                session.add(model)
            else:
                model.status = status
                model.details_json = _encode(envelope)
            session.flush()
            session.refresh(model)
            return self._record(model)

    def get(self, capability_id: str, content_digest: str) -> CapabilityVerificationRecord | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(CapabilityVerification).where(
                    CapabilityVerification.capability_id == capability_id,
                    CapabilityVerification.content_digest == content_digest,
                )
            )
            return None if model is None else self._record(model)

    @staticmethod
    def _record(model: CapabilityVerification) -> CapabilityVerificationRecord:
        envelope = _decode(model.details_json)
        return CapabilityVerificationRecord(
            capability_id=model.capability_id,
            content_digest=model.content_digest,
            scope=tuple(cast(list[str], envelope["scope"])),
            status=model.status,
            reason=cast(str, envelope["reason"]),
            details=cast(dict[str, JsonValue], envelope["details"]),
            verified_at=model.verified_at,
        )


class TrustDecision(StrEnum):
    SELECTED = "selected"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class TrustDecisionRecord:
    capability_id: str
    content_digest: str
    scope: tuple[str, ...]
    decision: TrustDecision
    permissions: tuple[str, ...]
    reason: str
    created_at: datetime


class TrustDecisionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        *,
        capability_id: str,
        content_digest: str,
        scope: Sequence[str],
        decision: TrustDecision,
        permissions: Sequence[str],
        reason: str,
    ) -> TrustDecisionRecord:
        envelope: dict[str, JsonValue] = {
            "scope": list(scope),
            "permissions": list(permissions),
            "reason": reason,
        }
        with self._session_factory.begin() as session:
            model = session.scalar(
                select(UserTrustDecision).where(
                    UserTrustDecision.capability_id == capability_id,
                    UserTrustDecision.content_digest == content_digest,
                )
            )
            if model is None:
                model = UserTrustDecision(
                    capability_id=capability_id,
                    content_digest=content_digest,
                    decision=decision.value,
                    permissions_json=_encode(envelope),
                )
                session.add(model)
            else:
                model.decision = decision.value
                model.permissions_json = _encode(envelope)
            session.flush()
            session.refresh(model)
            return self._record(model)

    def get(self, capability_id: str, content_digest: str) -> TrustDecisionRecord | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(UserTrustDecision).where(
                    UserTrustDecision.capability_id == capability_id,
                    UserTrustDecision.content_digest == content_digest,
                )
            )
            return None if model is None else self._record(model)

    @staticmethod
    def _record(model: UserTrustDecision) -> TrustDecisionRecord:
        envelope = _decode(model.permissions_json)
        return TrustDecisionRecord(
            capability_id=model.capability_id,
            content_digest=model.content_digest,
            scope=tuple(cast(list[str], envelope["scope"])),
            decision=TrustDecision(model.decision),
            permissions=tuple(cast(list[str], envelope["permissions"])),
            reason=cast(str, envelope["reason"]),
            created_at=model.created_at,
        )


@dataclass(frozen=True)
class AuditEventRecord:
    event_id: int
    run_id: str | None
    event_type: str
    summary: str
    details: dict[str, JsonValue]
    redacted: bool
    created_at: datetime


class AuditEventRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def write(
        self,
        *,
        event_type: str,
        summary: str,
        details: Mapping[str, JsonValue],
        run_id: str | None = None,
    ) -> AuditEventRecord:
        envelope: dict[str, JsonValue] = {
            "summary": summary,
            "details": _payload(details),
        }
        with self._session_factory.begin() as session:
            if run_id is not None and session.get(Run, run_id) is None:
                raise LookupError(f"run {run_id!r} does not exist")
            model = AuditEvent(
                run_id=run_id,
                event_type=event_type,
                event_json=_encode(envelope),
                redacted=True,
            )
            session.add(model)
            session.flush()
            session.refresh(model)
            return self._record(model)

    def get(self, event_id: int) -> AuditEventRecord | None:
        with self._session_factory() as session:
            model = session.get(AuditEvent, event_id)
            return None if model is None else self._record(model)

    def list_for_run(self, run_id: str) -> tuple[AuditEventRecord, ...]:
        """Return a run's audit trail in stable creation order."""
        with self._session_factory() as session:
            models = session.scalars(
                select(AuditEvent).where(AuditEvent.run_id == run_id).order_by(AuditEvent.id)
            )
            return tuple(self._record(model) for model in models)

    def list_for_task(self, task_id: str) -> tuple[AuditEventRecord, ...]:
        with self._session_factory() as session:
            models = session.scalars(
                select(AuditEvent)
                .join(TaskOutcomeRow, TaskOutcomeRow.audit_event_id == AuditEvent.id)
                .where(TaskOutcomeRow.task_id == task_id)
                .order_by(AuditEvent.id)
            )
            return tuple(self._record(model) for model in models)

    @staticmethod
    def _record(model: AuditEvent) -> AuditEventRecord:
        envelope = _decode(model.event_json)
        return AuditEventRecord(
            event_id=model.id,
            run_id=model.run_id,
            event_type=model.event_type,
            summary=cast(str, envelope["summary"]),
            details=cast(dict[str, JsonValue], envelope["details"]),
            redacted=model.redacted,
            created_at=model.created_at,
        )


@dataclass(frozen=True)
class TaskOutcomeRecord:
    task_id: str
    outcome: TaskOutcome
    created_at: datetime


class TaskOutcomeRepository:
    """Persist one idempotent low-sensitivity outcome and its audit event per task."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(self, task_id: str, outcome: TaskOutcome) -> TaskOutcomeRecord:
        payload = outcome.model_dump(mode="json")
        with self._session_factory.begin() as session:
            existing = session.scalar(
                select(TaskOutcomeRow).where(TaskOutcomeRow.task_id == task_id)
            )
            if existing is not None:
                return self._record(existing)
            row = TaskOutcomeRow(
                task_id=task_id,
                task_type=outcome.task_type,
                workflow=outcome.workflow,
                capabilities_used_json=_encode({"items": list(outcome.capabilities_used)}),
                verification_passed=outcome.verification_passed,
                user_rework=outcome.user_rework,
                unused_recommendations_json=_encode(
                    {"items": list(outcome.unused_recommendations)}
                ),
            )
            session.add(row)
            session.flush()
            event = AuditEvent(
                event_type="task.outcome.recorded",
                event_json=_encode(
                    {
                        "summary": "Recorded a low-sensitivity task outcome.",
                        "details": cast(dict[str, JsonValue], payload),
                    }
                ),
                redacted=True,
            )
            session.add(event)
            session.flush()
            row.audit_event_id = event.id
            session.flush()
            session.refresh(row)
            return self._record(row)

    def get(self, task_id: str) -> TaskOutcomeRecord:
        with self._session_factory() as session:
            row = session.scalar(select(TaskOutcomeRow).where(TaskOutcomeRow.task_id == task_id))
            if row is None:
                raise LookupError(f"task outcome {task_id!r} does not exist")
            return self._record(row)

    @staticmethod
    def _record(row: TaskOutcomeRow) -> TaskOutcomeRecord:
        used = cast(list[str], _decode(row.capabilities_used_json)["items"])
        unused = cast(list[str], _decode(row.unused_recommendations_json)["items"])
        return TaskOutcomeRecord(
            task_id=row.task_id,
            outcome=TaskOutcome(
                task_type=row.task_type,
                workflow=row.workflow,
                capabilities_used=tuple(used),
                verification_passed=row.verification_passed,
                user_rework=row.user_rework,
                unused_recommendations=tuple(unused),
            ),
            created_at=row.created_at,
        )
