from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from vibe.models import (
    Blueprint,
    CapabilityManifest,
    ContextCapsule,
    RepositorySnapshot,
    ResolutionPlan,
    Risk,
    TaskPlan,
)
from vibe.models.base import VersionedModel
from vibe.models.blueprint import LifecycleStage, ProjectConstraint
from vibe.models.capability import CapabilityKind, CapabilityScope, Permission
from vibe.models.capsule import SourceReference
from vibe.models.repository import FactConfidence, RepositoryFact
from vibe.models.resolution import CapabilityResolution, ResolutionStatus
from vibe.models.risk import RiskDimension, RiskFactor, RiskLevel
from vibe.models.task import TaskPhase, WorkflowMode


def minimal_models(tmp_path: Path) -> tuple[VersionedModel, ...]:
    risk = Risk(
        level=RiskLevel.LOW,
        factors=(
            RiskFactor(
                dimension=RiskDimension.SCOPE,
                level=RiskLevel.LOW,
                rationale="Single-file read-only change.",
            ),
        ),
    )
    return (
        Blueprint(
            project_name="orchestrator",
            goal="Compile project capabilities into task context.",
            lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
            risk_level=RiskLevel.LOW,
            repository_digest="01234567",
        ),
        RepositorySnapshot(
            root=tmp_path,
            is_empty=True,
            source_digest="01234567",
        ),
        CapabilityManifest(
            capability_id="local.repo-reader",
            name="Repository reader",
            kind=CapabilityKind.CLI_TOOL,
            scope=CapabilityScope.PROJECT,
            source="rg",
            provides=("repository-search",),
            content_digest="01234567",
        ),
        ResolutionPlan(
            blueprint_digest="01234567",
            inventory_digest="89abcdef",
            resolutions=(),
        ),
        TaskPlan(
            task_id="task-1",
            intent="Inspect repository",
            risk_level=RiskLevel.LOW,
            workflow_mode=WorkflowMode.FAST,
            acceptance_criteria=("Report facts",),
            phases=(
                TaskPhase(
                    phase_id="inspect",
                    objective="Inspect the repository",
                    completion_conditions=("Facts collected",),
                ),
            ),
        ),
        risk,
        ContextCapsule(
            task_id="task-1",
            intent="Inspect repository",
            scope=("src",),
            acceptance_criteria=("Report facts",),
            current_phase="inspect",
            sources=(SourceReference(source_id="repository", digest="01234567"),),
            invalidation_conditions=("repository changes",),
            token_budget=2_000,
        ),
    )


def complete_models(tmp_path: Path) -> tuple[VersionedModel, ...]:
    return (
        Blueprint(
            project_name="orchestrator",
            goal="Compile project capabilities into task context.",
            lifecycle_stage=LifecycleStage.PRODUCTION,
            risk_level=RiskLevel.HIGH,
            target_platforms=("codex", "claude-code"),
            constraints=(ProjectConstraint(name="python", value="3.12", locked=True),),
            preferences={"local_first": True, "max_parallel": 2},
            repository_digest="01234567",
        ),
        RepositorySnapshot(
            root=tmp_path,
            is_empty=False,
            git_root=tmp_path,
            head="a" * 40,
            dirty=False,
            facts=(
                RepositoryFact(
                    key="languages",
                    value=["python"],
                    confidence=FactConfidence.CONFIRMED,
                    sources=("pyproject.toml",),
                ),
            ),
            source_digest="01234567",
        ),
        CapabilityManifest(
            capability_id="local.repo-reader",
            name="Repository reader",
            kind=CapabilityKind.CLI_TOOL,
            scope=CapabilityScope.USER,
            source="C:/tools/rg.exe",
            provides=("repository-search", "text-search"),
            permissions=frozenset({Permission.READ_PROJECT, Permission.EXECUTE_COMMAND}),
            version="14.1.0",
            content_digest="01234567",
            verified=True,
        ),
        ResolutionPlan(
            blueprint_digest="01234567",
            inventory_digest="89abcdef",
            resolutions=(
                CapabilityResolution(
                    requirement="repository-search",
                    status=ResolutionStatus.SELECTED,
                    capability_id="local.repo-reader",
                    reason="Verified local capability",
                ),
            ),
        ),
        TaskPlan(
            task_id="task-1",
            intent="Implement feature",
            risk_level=RiskLevel.HIGH,
            workflow_mode=WorkflowMode.RIGOROUS,
            acceptance_criteria=("Tests pass",),
            phases=(
                TaskPhase(
                    phase_id="implement",
                    objective="Implement the feature",
                    completion_conditions=("Focused tests pass",),
                    capability_ids=("local.repo-reader",),
                    requires_approval=True,
                ),
            ),
        ),
        Risk(
            level=RiskLevel.HIGH,
            factors=(
                RiskFactor(
                    dimension=RiskDimension.DATA_SENSITIVITY,
                    level=RiskLevel.HIGH,
                    rationale="Touches sensitive configuration.",
                    mitigations=("Redact secrets",),
                ),
                RiskFactor(
                    dimension=RiskDimension.REVERSIBILITY,
                    level=RiskLevel.MEDIUM,
                    rationale="Rollback is available.",
                ),
            ),
            requires_approval=True,
            rollback_required=True,
        ),
        ContextCapsule(
            task_id="task-1",
            intent="Implement feature",
            scope=("src", "tests"),
            constraints=("Do not access secrets",),
            acceptance_criteria=("Tests pass",),
            current_phase="implement",
            selected_capability_ids=("local.repo-reader",),
            deferred_capability_ids=("local.memory",),
            rejected_capability_ids=("remote.writer",),
            sources=(
                SourceReference(source_id="blueprint", digest="01234567"),
                SourceReference(source_id="repository", digest="89abcdef"),
            ),
            invalidation_conditions=("HEAD changes", "scope changes"),
            token_budget=4_000,
        ),
    )


@pytest.mark.parametrize("fixture_name", ["minimal", "complete"])
def test_all_top_level_models_round_trip(
    fixture_name: str,
    tmp_path: Path,
) -> None:
    fixtures = minimal_models(tmp_path) if fixture_name == "minimal" else complete_models(tmp_path)

    assert len(fixtures) == 7
    for model in fixtures:
        model_type = type(model)
        assert model_type.model_validate_json(model.model_dump_json()) == model


def test_project_owned_models_reject_dangerous_unknown_fields() -> None:
    data: dict[str, Any] = {
        "project_name": "orchestrator",
        "goal": "Build it",
        "lifecycle_stage": "active-development",
        "risk_level": "medium",
        "repository_digest": "01234567",
        "shell_command": "rm -rf /",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Blueprint.model_validate(data)


def test_unknown_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported schema_version"):
        Blueprint(
            schema_version="99",
            project_name="orchestrator",
            goal="Build it",
            lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
            risk_level=RiskLevel.LOW,
            repository_digest="01234567",
        )


def test_invalid_capability_permission_is_rejected() -> None:
    data = {
        "capability_id": "local.repo-reader",
        "name": "Repository reader",
        "kind": "cli-tool",
        "scope": "project",
        "source": "rg",
        "provides": ["repository-search"],
        "permissions": ["read-secrets"],
        "content_digest": "01234567",
    }

    with pytest.raises(ValidationError, match="permissions"):
        CapabilityManifest.model_validate(data)


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (RepositorySnapshot, {"root": ".", "is_empty": True}),
        (SourceReference, {"source_id": "blueprint"}),
    ],
)
def test_source_backed_models_require_digests(
    model: type[object],
    data: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="digest"):
        model.model_validate(data)  # type: ignore[attr-defined]


def test_selected_resolution_requires_capability_id() -> None:
    with pytest.raises(ValidationError, match="capability_id"):
        CapabilityResolution(
            requirement="repository-search",
            status=ResolutionStatus.SELECTED,
            reason="Selected",
        )


def test_task_phase_ids_are_unique() -> None:
    phase = TaskPhase(
        phase_id="verify",
        objective="Verify",
        completion_conditions=("Tests pass",),
    )

    with pytest.raises(ValidationError, match="phase_id"):
        TaskPlan(
            task_id="task-1",
            intent="Verify",
            risk_level=RiskLevel.LOW,
            workflow_mode=WorkflowMode.FAST,
            acceptance_criteria=("Tests pass",),
            phases=(phase, phase),
        )