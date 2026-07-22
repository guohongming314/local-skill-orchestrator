from __future__ import annotations

from collections.abc import Mapping

import pytest

from vibe.conversation.structured_result import (
    DecisionLockedError,
    StructuredResultError,
    ValueSource,
    apply_revision,
    lock_decisions,
    parse_structured_result,
)
from vibe.models.decisions import (
    AuthorizationState,
    NetworkPolicy,
    RuntimeNetwork,
    TriState,
)


def valid_payload() -> dict[str, object]:
    return {
        "blueprint": {
            "project_name": "orchestrator",
            "goal": "Compile local capabilities",
            "lifecycle_stage": "active-development",
            "risk_level": "medium",
            "constraints": [{"name": "network", "value": "local-first"}],
            "preferences": {"testing": "test-first"},
            "repository_digest": "01234567",
        },
        "field_sources": {
            "project_name": "inferred",
            "goal": "confirmed",
            "lifecycle_stage": "inferred",
            "risk_level": "confirmed",
        },
        "locked_decisions": ["goal"],
    }


def test_valid_result_produces_blueprint_with_provenance() -> None:
    result = parse_structured_result(valid_payload())

    assert result.blueprint.project_name == "orchestrator"
    assert result.blueprint.goal == "Compile local capabilities"
    assert result.field_sources["project_name"] is ValueSource.INFERRED
    assert result.field_sources["goal"] is ValueSource.CONFIRMED
    assert result.locked_decisions == frozenset({"goal"})


def test_existing_result_without_decisions_gets_unknown_defaults() -> None:
    result = parse_structured_result(valid_payload())

    decisions = result.blueprint.decisions
    permission_values = (
        decisions.read_project.value,
        decisions.write_project.value,
        decisions.execute_command.value,
        decisions.write_outside_project.value,
        decisions.access_secrets.value,
    )

    assert permission_values == (TriState.UNKNOWN,) * 5
    assert decisions.network_policy.value is NetworkPolicy.UNKNOWN
    assert decisions.discovery_approval is AuthorizationState.NOT_REQUESTED
    assert decisions.artifact_fetch_approval is AuthorizationState.NOT_REQUESTED
    assert decisions.candidate_runtime_network is RuntimeNetwork.UNKNOWN


def test_invalid_result_repairs_once() -> None:
    calls: list[tuple[Mapping[str, object], tuple[str, ...]]] = []

    def repair(
        payload: Mapping[str, object], diagnostics: tuple[str, ...]
    ) -> Mapping[str, object]:
        calls.append((payload, diagnostics))
        return valid_payload()

    result = parse_structured_result(
        {"blueprint": {"project_name": ""}}, repair=repair
    )

    assert result.blueprint.goal == "Compile local capabilities"
    assert len(calls) == 1
    assert any("blueprint" in diagnostic for diagnostic in calls[0][1])


def test_invalid_repair_fails_with_field_level_diagnostics() -> None:
    repairs = 0

    def broken_repair(
        _payload: Mapping[str, object], _diagnostics: tuple[str, ...]
    ) -> Mapping[str, object]:
        nonlocal repairs
        repairs += 1
        return {"blueprint": {"project_name": "still incomplete"}}

    with pytest.raises(StructuredResultError) as caught:
        parse_structured_result({}, repair=broken_repair)

    assert repairs == 1
    assert any("blueprint" in diagnostic for diagnostic in caught.value.diagnostics)
    assert any("field_sources" in diagnostic for diagnostic in caught.value.diagnostics)


def test_locked_decisions_cannot_be_overwritten_by_later_inference() -> None:
    result = parse_structured_result(valid_payload())

    with pytest.raises(DecisionLockedError, match="goal"):
        apply_revision(
            result,
            {"goal": "A later model guess"},
            source=ValueSource.INFERRED,
        )

    assert result.blueprint.goal == "Compile local capabilities"


def test_user_revision_can_be_locked_and_other_fields_remain_revisable() -> None:
    result = parse_structured_result(valid_payload())
    revised = apply_revision(
        result,
        {"project_name": "local-orchestrator"},
        source=ValueSource.CONFIRMED,
    )
    locked = lock_decisions(revised, "project_name")

    assert locked.blueprint.project_name == "local-orchestrator"
    assert locked.field_sources["project_name"] is ValueSource.CONFIRMED
    assert locked.locked_decisions == frozenset({"goal", "project_name"})

    with pytest.raises(DecisionLockedError, match="project_name"):
        apply_revision(
            locked,
            {"project_name": "model-overwrite"},
            source=ValueSource.INFERRED,
        )
