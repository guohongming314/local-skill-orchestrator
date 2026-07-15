from __future__ import annotations

from pathlib import Path

from vibe.practices.calibration import (
    CalibrationOutcome,
    confirm_suggestion,
    load_confirmed_overrides,
    pending_suggestions,
    reject_suggestion,
)
from vibe.practices.models import RequirementStrength


def outcomes(*, count: int, capability: str = "cap.memory") -> tuple[CalibrationOutcome, ...]:
    return tuple(
        CalibrationOutcome(
            task_id=f"task-{index}",
            unused_recommendations=(capability,),
        )
        for index in range(1, count + 1)
    )


def test_n_unused_outcomes_propose_explainable_demotion(tmp_path: Path) -> None:
    assert pending_suggestions(tmp_path, outcomes(count=2)) == ()

    suggestions = pending_suggestions(tmp_path, outcomes(count=3))

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.capability == "cap.memory"
    assert suggestion.current_strength is RequirementStrength.RECOMMENDED
    assert suggestion.proposed_strength is RequirementStrength.OPTIONAL
    assert suggestion.rule == "unused-recommendation-at-least-3"
    assert suggestion.evidence == ("task-1", "task-2", "task-3")
    assert load_confirmed_overrides(tmp_path) == ()


def test_user_rejection_is_persisted_and_stops_reproposing(tmp_path: Path) -> None:
    suggestion = pending_suggestions(tmp_path, outcomes(count=3))[0]

    reject_suggestion(tmp_path, suggestion)

    assert pending_suggestions(tmp_path, outcomes(count=4)) == ()
    state = (tmp_path / ".ai-project" / "calibration.yaml").read_text(encoding="utf-8")
    assert "rejected" in state
    assert "outcome-calibration" in state


def test_confirmed_calibration_becomes_project_override_with_provenance(
    tmp_path: Path,
) -> None:
    suggestion = pending_suggestions(tmp_path, outcomes(count=3))[0]

    confirm_suggestion(tmp_path, suggestion)

    overrides = load_confirmed_overrides(tmp_path)
    assert len(overrides) == 1
    assert overrides[0].capability == "cap.memory"
    assert overrides[0].strength is RequirementStrength.OPTIONAL
    assert overrides[0].provenance == "outcome-calibration"
    assert pending_suggestions(tmp_path, outcomes(count=4)) == ()


def test_doctor_surfaces_pending_calibration_with_rule_and_outcomes(tmp_path: Path) -> None:
    from alembic import command
    from sqlalchemy.orm import Session, sessionmaker

    from vibe.doctor.checks import CalibrationSuggestionsCheck, DoctorContext
    from vibe.inventory.service import InventoryResult
    from vibe.models.outcome import TaskOutcome
    from vibe.persistence.database import create_sqlite_engine, migration_config
    from vibe.persistence.repositories import TaskOutcomeRepository

    database = tmp_path / "state.sqlite3"
    command.upgrade(migration_config(database), "head")
    repository = TaskOutcomeRepository(
        sessionmaker(create_sqlite_engine(database), class_=Session, expire_on_commit=False)
    )
    for index in range(1, 4):
        repository.record(
            f"task-{index}",
            TaskOutcome(
                task_type="bug-fix",
                workflow="standard",
                capabilities_used=(),
                verification_passed=True,
                user_rework=False,
                unused_recommendations=("cap.memory",),
            ),
        )

    findings = CalibrationSuggestionsCheck(database).check(
        DoctorContext(
            root=tmp_path,
            inventory=InventoryResult(
                capabilities=(), diagnostics=(), inventory_digest="empty123"
            ),
            command_resolver=lambda command: command,
        )
    )

    assert len(findings) == 1
    assert findings[0].code == "outcome.calibration-pending"
    assert findings[0].evidence == (
        "cap.memory",
        "unused-recommendation-at-least-3",
        "task-1",
        "task-2",
        "task-3",
    )
    assert "confirm" in findings[0].remediation.lower()


def test_confirmed_calibration_changes_future_project_resolution(tmp_path: Path) -> None:
    from vibe.commands.project_plan import build_project_plan
    from vibe.inventory.service import InventoryResult
    from vibe.models.blueprint import Blueprint, LifecycleStage
    from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot
    from vibe.models.risk import RiskLevel

    suggestion = pending_suggestions(
        tmp_path, outcomes(count=3, capability="browser.validation")
    )[0]
    confirm_suggestion(tmp_path, suggestion)
    blueprint = Blueprint(
        project_name="web-demo",
        goal="Build a web application",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        repository_digest="12345678",
    )
    repository = RepositorySnapshot(
        root=tmp_path,
        is_empty=False,
        facts=(
            RepositoryFact(
                key="project_type",
                value="web-application",
                confidence=FactConfidence.CONFIRMED,
                sources=("fixture",),
            ),
        ),
        source_digest="abcdefgh",
    )

    plan = build_project_plan(
        tmp_path,
        blueprint,
        repository,
        inventory=InventoryResult(
            capabilities=(), diagnostics=(), inventory_digest="empty123"
        ),
    )
    requirement = next(
        item for item in plan.requirements if item.capability == "browser.validation"
    )

    assert requirement.strength is RequirementStrength.OPTIONAL
    assert requirement.override_provenance == "outcome-calibration"
