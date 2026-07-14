from __future__ import annotations

from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    ScopeLevel,
    TaskOperation,
)
from vibe.workflows.scenarios import (
    ScenarioClassification,
    ScenarioId,
    ScenarioRequest,
    classify_scenario,
)
from vibe.workflows.task_graph import build_task_plan


def classification(
    scenario: ScenarioId,
    *,
    operations: frozenset[TaskOperation],
    sensitivity: DataSensitivity = DataSensitivity.PUBLIC,
    scope: ScopeLevel = ScopeLevel.LOCAL,
    reversibility: Reversibility = Reversibility.REVERSIBLE,
) -> ScenarioClassification:
    return classify_scenario(
        ScenarioRequest(
            scenario=scenario,
            scope=scope,
            data_sensitivity=sensitivity,
            reversibility=reversibility,
            operations=operations,
        )
    )


def test_standard_write_workflow_has_explicit_ordered_completion_gates() -> None:
    task = classification(
        ScenarioId.BUG,
        operations=frozenset({TaskOperation.WRITE_PROJECT}),
    )

    plan = build_task_plan(
        "task-1",
        "Fix the UI bug",
        task,
        acceptance_criteria=("The UI behaves correctly",),
    )

    assert tuple(phase.phase_id for phase in plan.phases) == (
        "inspect",
        "design",
        "implement",
        "verify",
        "review",
    )
    assert all(phase.completion_conditions for phase in plan.phases)


def test_read_only_review_omits_mutation_and_rollback_phases() -> None:
    task = classification(
        ScenarioId.REVIEW,
        operations=frozenset({TaskOperation.READ_PROJECT}),
    )

    plan = build_task_plan(
        "task-2",
        "Review the change",
        task,
        acceptance_criteria=("Findings are actionable",),
    )

    ids = {phase.phase_id for phase in plan.phases}
    assert "implement" not in ids
    assert "rollback" not in ids
    assert "approval" not in ids


def test_high_risk_write_workflow_requires_approval_and_rollback_preparation() -> None:
    task = classification(
        ScenarioId.BUG,
        sensitivity=DataSensitivity.REGULATED,
        operations=frozenset(
            {TaskOperation.WRITE_PROJECT, TaskOperation.HANDLE_PAYMENT}
        ),
    )

    plan = build_task_plan(
        "task-3",
        "Fix payment processing",
        task,
        acceptance_criteria=("Payments remain consistent",),
    )

    phases = {phase.phase_id: phase for phase in plan.phases}
    assert phases["approval"].requires_approval
    assert "rollback" in phases
    assert tuple(phases) == (
        "inspect",
        "design",
        "approval",
        "rollback",
        "implement",
        "verify",
        "review",
    )


def test_phase_capabilities_are_bound_without_granting_extra_permissions() -> None:
    task = classification(
        ScenarioId.FEATURE,
        operations=frozenset({TaskOperation.WRITE_PROJECT}),
    )

    plan = build_task_plan(
        "task-4",
        "Add a feature",
        task,
        acceptance_criteria=("Feature works",),
        capabilities={
            "inspect": ("repo.reader",),
            "implement": ("editor.safe",),
            "verify": ("cli.pytest",),
        },
    )

    bound = {phase.phase_id: phase.capability_ids for phase in plan.phases}
    assert bound["inspect"] == ("repo.reader",)
    assert bound["implement"] == ("editor.safe",)
    assert bound["verify"] == ("cli.pytest",)
    assert bound["design"] == ()
