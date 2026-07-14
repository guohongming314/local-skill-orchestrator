from __future__ import annotations

from pathlib import Path

import yaml
from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from vibe.doctor.checks import DoctorContext, OutcomeInsightsCheck
from vibe.doctor.report import Severity
from vibe.inventory.service import InventoryResult
from vibe.materialize.templates import CapabilityLock, CapabilityLockEntry
from vibe.models.outcome import TaskOutcome
from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.repositories import TaskOutcomeRepository


def seed_outcomes(database: Path, outcomes: tuple[TaskOutcome, ...]) -> None:
    command.upgrade(migration_config(database), "head")
    factory = sessionmaker(
        create_sqlite_engine(database), class_=Session, expire_on_commit=False
    )
    repository = TaskOutcomeRepository(factory)
    for index, outcome in enumerate(outcomes, start=1):
        repository.record(f"task-{index}", outcome)


def outcome(
    *,
    used: tuple[str, ...] = ("cap.used",),
    passed: bool = True,
    unused: tuple[str, ...] = (),
) -> TaskOutcome:
    return TaskOutcome(
        task_type="bug-fix",
        workflow="standard",
        capabilities_used=used,
        verification_passed=passed,
        user_rework=False,
        unused_recommendations=unused,
    )


def context(root: Path) -> DoctorContext:
    return DoctorContext(
        root=root,
        inventory=InventoryResult(capabilities=(), diagnostics=(), inventory_digest="empty"),
        command_resolver=lambda command: command,
    )


def write_lock(root: Path, *provider_ids: str) -> None:
    lock = CapabilityLock(
        inventory_digest="inventory-digest",
        providers=tuple(
            CapabilityLockEntry(
                provider_id=provider_id,
                kind="agent-skill",
                scope="project",
                source=provider_id,
                content_digest="digest-1234",
            )
            for provider_id in provider_ids
        ),
    )
    target = root / ".ai-project" / "capabilities.lock"
    target.parent.mkdir(parents=True)
    target.write_text(
        yaml.safe_dump(lock.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )


def test_empty_outcome_store_produces_no_insight_noise(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    seed_outcomes(database, ())
    write_lock(tmp_path, "cap.unused")

    assert OutcomeInsightsCheck(database).check(context(tmp_path)) == ()


def test_installed_but_never_used_triggers_at_threshold_not_below(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    seed_outcomes(database, tuple(outcome() for _ in range(3)))
    write_lock(tmp_path, "cap.used", "cap.unused")
    check = OutcomeInsightsCheck(database)

    findings = check.check(context(tmp_path))
    finding = next(item for item in findings if item.code == "outcome.capability-unused")

    assert finding.severity is Severity.ACTIONABLE
    assert finding.evidence == ("cap.unused", "task-1", "task-2", "task-3")
    assert "remove" in finding.remediation.lower() or "need" in finding.remediation.lower()

    below = tmp_path / "below-unused.sqlite3"
    seed_outcomes(below, tuple(outcome() for _ in range(2)))
    assert not any(
        item.code == "outcome.capability-unused"
        for item in OutcomeInsightsCheck(below).check(context(tmp_path))
    )


def test_repeated_override_triggers_at_three_not_below(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    seed_outcomes(
        database,
        tuple(outcome(unused=("cap.recommended",)) for _ in range(3)),
    )
    check = OutcomeInsightsCheck(database)

    findings = check.check(context(tmp_path))
    finding = next(item for item in findings if item.code == "outcome.recommendation-overridden")

    assert finding.severity is Severity.ACTIONABLE
    assert finding.evidence == ("cap.recommended", "task-1", "task-2", "task-3")
    assert "policy" in finding.remediation.lower()
    assert "review" in finding.remediation.lower()

    below = tmp_path / "below-override.sqlite3"
    seed_outcomes(
        below,
        tuple(outcome(unused=("cap.recommended",)) for _ in range(2)),
    )
    assert not any(
        item.code == "outcome.recommendation-overridden"
        for item in OutcomeInsightsCheck(below).check(context(tmp_path))
    )


def test_repeated_verification_failure_triggers_at_three_not_below(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    seed_outcomes(
        database,
        tuple(outcome(used=("cap.flaky",), passed=False) for _ in range(3)),
    )
    check = OutcomeInsightsCheck(database)

    findings = check.check(context(tmp_path))
    finding = next(item for item in findings if item.code == "outcome.verification-failing")

    assert finding.severity is Severity.ACTIONABLE
    assert finding.evidence == ("cap.flaky", "task-1", "task-2", "task-3")
    assert "fallback" in finding.remediation.lower()
    assert "provider" in finding.remediation.lower()

    below = tmp_path / "below-failure.sqlite3"
    seed_outcomes(
        below,
        tuple(outcome(used=("cap.flaky",), passed=False) for _ in range(2)),
    )
    assert not any(
        item.code == "outcome.verification-failing"
        for item in OutcomeInsightsCheck(below).check(context(tmp_path))
    )
