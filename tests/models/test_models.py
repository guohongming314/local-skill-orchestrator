import pytest
from pydantic import ValidationError

from vibe.models.blueprint import Blueprint, LifecycleStage, RiskLevel
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)
from vibe.models.capsule import ContextCapsule, SourceReference


def test_blueprint_round_trip() -> None:
    blueprint = Blueprint(
        project_name="orchestrator",
        goal="Compile project capabilities into task context.",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        repository_digest="01234567",
    )

    assert Blueprint.model_validate_json(blueprint.model_dump_json()) == blueprint


def test_project_owned_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Blueprint.model_validate(
            {
                "project_name": "orchestrator",
                "goal": "Build it",
                "lifecycle_stage": "active-development",
                "risk_level": "medium",
                "repository_digest": "01234567",
                "shell_command": "rm -rf /",
            }
        )


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


def test_capability_permissions_are_enums() -> None:
    manifest = CapabilityManifest(
        capability_id="local.repo-reader",
        name="Repository reader",
        kind=CapabilityKind.CLI_TOOL,
        scope=CapabilityScope.PROJECT,
        source="/usr/bin/rg",
        provides=("repository-search",),
        permissions=frozenset({Permission.READ_PROJECT}),
        content_digest="01234567",
    )

    assert manifest.permissions == {Permission.READ_PROJECT}


def test_capsule_requires_source_digest() -> None:
    with pytest.raises(ValidationError):
        SourceReference(source_id="blueprint", digest="short")


def test_capsule_capability_states_must_not_overlap() -> None:
    with pytest.raises(ValidationError, match="must be disjoint"):
        ContextCapsule(
            task_id="task-1",
            intent="Inspect repository",
            scope=("src",),
            acceptance_criteria=("Report facts",),
            current_phase="inspect",
            selected_capability_ids=("local.rg",),
            rejected_capability_ids=("local.rg",),
            sources=(SourceReference(source_id="blueprint", digest="01234567"),),
            invalidation_conditions=("repository HEAD changes",),
            token_budget=2_000,
        )
