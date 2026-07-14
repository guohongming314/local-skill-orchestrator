from __future__ import annotations

from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    ScopeLevel,
    TaskOperation,
)
from vibe.models.task import WorkflowMode
from vibe.workflows.scenarios import (
    P0_SCENARIOS,
    SCENARIO_FIXTURES,
    SCENARIO_REGISTRY,
    ScenarioId,
    ScenarioRequest,
    classify_scenario,
)


def request(
    scenario: ScenarioId,
    *,
    scope: ScopeLevel = ScopeLevel.LOCAL,
    sensitivity: DataSensitivity = DataSensitivity.PUBLIC,
    reversibility: Reversibility = Reversibility.REVERSIBLE,
    operations: frozenset[TaskOperation] = frozenset({TaskOperation.WRITE_PROJECT}),
) -> ScenarioRequest:
    return ScenarioRequest(
        scenario=scenario,
        scope=scope,
        data_sensitivity=sensitivity,
        reversibility=reversibility,
        operations=operations,
    )


def test_registry_contains_six_complete_p0_and_all_p1_scenarios() -> None:
    assert frozenset(
        {
            ScenarioId.BUG,
            ScenarioId.FEATURE,
            ScenarioId.REFACTOR,
            ScenarioId.SECURITY,
            ScenarioId.MIGRATION,
            ScenarioId.REVIEW,
        }
    ) == P0_SCENARIOS
    assert set(SCENARIO_REGISTRY) == set(ScenarioId)
    assert set(SCENARIO_FIXTURES) == set(ScenarioId)
    assert all(definition.risk_policy for definition in SCENARIO_REGISTRY.values())
    assert all(definition.safe_fallback for definition in SCENARIO_REGISTRY.values())


def test_simple_ui_bug_uses_standard_or_faster_workflow() -> None:
    classification = classify_scenario(request(ScenarioId.BUG))

    assert classification.workflow_mode in {WorkflowMode.FAST, WorkflowMode.STANDARD}
    assert not classification.risk.requires_approval
    assert classification.explanation


def test_payment_bug_is_rigorous_and_requires_approval() -> None:
    classification = classify_scenario(
        request(
            ScenarioId.BUG,
            sensitivity=DataSensitivity.REGULATED,
            operations=frozenset(
                {TaskOperation.WRITE_PROJECT, TaskOperation.HANDLE_PAYMENT}
            ),
        )
    )

    assert classification.workflow_mode is WorkflowMode.RIGOROUS
    assert classification.risk.requires_approval
    assert "approval" in classification.required_phases


def test_read_only_review_has_no_write_or_approval_phase() -> None:
    classification = classify_scenario(
        request(
            ScenarioId.REVIEW,
            operations=frozenset({TaskOperation.READ_PROJECT}),
        )
    )

    assert not classification.includes_write_phase
    assert "write" not in classification.required_phases
    assert "approval" not in classification.required_phases


def test_migration_requires_rollback_and_approval_phases() -> None:
    classification = classify_scenario(
        request(
            ScenarioId.MIGRATION,
            scope=ScopeLevel.CROSS_SYSTEM,
            reversibility=Reversibility.DIFFICULT,
            operations=frozenset(
                {TaskOperation.WRITE_PROJECT, TaskOperation.MIGRATE_DATA}
            ),
        )
    )

    assert classification.workflow_mode is WorkflowMode.RIGOROUS
    assert classification.risk.rollback_required
    assert classification.risk.requires_approval
    assert {"approval", "rollback"} <= set(classification.required_phases)


def test_risk_factors_cover_all_dimensions_and_are_deterministic() -> None:
    task = request(
        ScenarioId.FEATURE,
        scope=ScopeLevel.MULTI_COMPONENT,
        sensitivity=DataSensitivity.SENSITIVE,
        reversibility=Reversibility.DIFFICULT,
        operations=frozenset({TaskOperation.WRITE_PROJECT, TaskOperation.NETWORK}),
    )

    first = classify_scenario(task)
    second = classify_scenario(task)

    assert first == second
    assert {factor.dimension.value for factor in first.risk.factors} == {
        "scope",
        "data-sensitivity",
        "reversibility",
        "operations",
    }
