from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.repositories import (
    AuditEventRepository,
    CapabilityVerificationRepository,
    InventoryCacheRepository,
    SecretLikePayloadError,
    TrustDecision,
    TrustDecisionRepository,
)


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database = tmp_path / "state.sqlite3"
    command.upgrade(migration_config(database), "head")
    return sessionmaker(create_sqlite_engine(database), expire_on_commit=False)


def test_inventory_cache_lookup_respects_digest_and_scope(
    session_factory: sessionmaker[Session],
) -> None:
    repository = InventoryCacheRepository(session_factory)
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    stored = repository.put(
        source_digest="inventory-1234",
        scope=("project", "user"),
        snapshot={"capability_ids": ["local.repo-reader"]},
        expires_at=expires_at,
    )

    assert stored.source_digest == "inventory-1234"
    assert stored.scope == ("project", "user")
    assert stored.snapshot == {"capability_ids": ["local.repo-reader"]}
    assert repository.get("inventory-1234", ("project", "user")) == stored
    assert repository.get("inventory-1234", ("project",)) is None
    assert repository.get("different-digest", ("project", "user")) is None


def test_inventory_cache_does_not_return_expired_entries(
    session_factory: sessionmaker[Session],
) -> None:
    repository = InventoryCacheRepository(session_factory)
    expires_at = datetime(2026, 1, 2, tzinfo=UTC)
    repository.put(
        source_digest="inventory-1234",
        scope=("project",),
        snapshot={"capability_ids": []},
        expires_at=expires_at,
    )

    assert (
        repository.get(
            "inventory-1234",
            ("project",),
            as_of=expires_at + timedelta(seconds=1),
        )
        is None
    )


def test_capability_verification_round_trips_scope_reason_and_details(
    session_factory: sessionmaker[Session],
) -> None:
    repository = CapabilityVerificationRepository(session_factory)

    stored = repository.record(
        capability_id="local.repo-reader",
        content_digest="capability-1234",
        scope=("project",),
        status="verified",
        reason="Manifest and executable digest match.",
        details={"adapter": "cli"},
    )

    assert repository.get("local.repo-reader", "capability-1234") == stored
    assert stored.scope == ("project",)
    assert stored.reason == "Manifest and executable digest match."
    assert stored.details == {"adapter": "cli"}


@pytest.mark.parametrize(
    "decision",
    [TrustDecision.SELECTED, TrustDecision.REJECTED, TrustDecision.DEFERRED],
)
def test_trust_decisions_retain_each_reason(
    decision: TrustDecision,
    session_factory: sessionmaker[Session],
) -> None:
    repository = TrustDecisionRepository(session_factory)
    reason = f"User chose {decision.value} after reviewing permissions."

    stored = repository.record(
        capability_id="local.repo-reader",
        content_digest=f"digest-{decision.value}",
        scope=("project",),
        decision=decision,
        permissions=("read-project",),
        reason=reason,
    )

    assert stored.decision is decision
    assert stored.reason == reason
    assert stored.permissions == ("read-project",)
    assert repository.get("local.repo-reader", f"digest-{decision.value}") == stored


def test_audit_events_store_redacted_typed_summaries(
    session_factory: sessionmaker[Session],
) -> None:
    repository = AuditEventRepository(session_factory)

    stored = repository.write(
        event_type="trust-decision-recorded",
        summary="Recorded a project-scoped trust decision.",
        details={"capability_id": "local.repo-reader", "decision": "selected"},
    )

    assert stored.redacted is True
    assert stored.summary == "Recorded a project-scoped trust decision."
    assert stored.details["decision"] == "selected"
    assert repository.get(stored.event_id) == stored


def test_inventory_rejects_nested_secret_fields(
    session_factory: sessionmaker[Session],
) -> None:
    repository = InventoryCacheRepository(session_factory)

    with pytest.raises(SecretLikePayloadError, match="secret-like field"):
        repository.put(
            source_digest="inventory-1234",
            scope=("project",),
            snapshot={"nested": {"api_token": "do-not-store"}},
        )


def test_verification_rejects_secret_fields(
    session_factory: sessionmaker[Session],
) -> None:
    repository = CapabilityVerificationRepository(session_factory)

    with pytest.raises(SecretLikePayloadError, match="secret-like field"):
        repository.record(
            capability_id="local.repo-reader",
            content_digest="capability-1234",
            scope=("project",),
            status="verified",
            reason="Verified.",
            details={"password": "do-not-store"},
        )


def test_audit_rejects_secret_fields(
    session_factory: sessionmaker[Session],
) -> None:
    repository = AuditEventRepository(session_factory)

    with pytest.raises(SecretLikePayloadError, match="secret-like field"):
        repository.write(
            event_type="unsafe",
            summary="Unsafe event.",
            details={"credentials": {"value": "do-not-store"}},
        )
