"""Compile scenario classifications into explicit phased task plans."""

from __future__ import annotations

from collections.abc import Mapping

from vibe.models.task import TaskPhase, TaskPlan, WorkflowMode
from vibe.workflows.phases import PHASE_TEMPLATES
from vibe.workflows.scenarios import ScenarioClassification


def build_task_plan(
    task_id: str,
    intent: str,
    classification: ScenarioClassification,
    *,
    acceptance_criteria: tuple[str, ...],
    capabilities: Mapping[str, tuple[str, ...]] | None = None,
) -> TaskPlan:
    """Build a deterministic plan whose phases match risk and mutation needs."""
    capability_map = capabilities or {}
    phase_ids = _phase_ids(classification)
    phases = tuple(
        _phase(
            phase_id,
            capability_map.get(phase_id, ()),
            requires_approval=phase_id == "approval",
        )
        for phase_id in phase_ids
    )
    return TaskPlan(
        task_id=task_id,
        intent=intent,
        risk_level=classification.risk.level,
        workflow_mode=classification.workflow_mode,
        acceptance_criteria=acceptance_criteria,
        phases=phases,
    )


def _phase_ids(classification: ScenarioClassification) -> tuple[str, ...]:
    write = classification.includes_write_phase
    approval = classification.risk.requires_approval
    rigorous = classification.workflow_mode is WorkflowMode.RIGOROUS

    if classification.workflow_mode is WorkflowMode.FAST:
        ids = ["inspect"]
        if approval:
            ids.append("approval")
        if write:
            ids.append("implement")
        ids.append("verify")
        return tuple(ids)

    ids = ["inspect", "design"]
    if approval:
        ids.append("approval")
    if write and (rigorous or classification.risk.rollback_required):
        ids.append("rollback")
    if write:
        ids.append("implement")
    ids.extend(("verify", "review"))
    return tuple(ids)


def _phase(
    phase_id: str,
    capability_ids: tuple[str, ...],
    *,
    requires_approval: bool,
) -> TaskPhase:
    template = PHASE_TEMPLATES[phase_id]
    return TaskPhase(
        phase_id=template.phase_id,
        objective=template.objective,
        completion_conditions=template.completion_conditions,
        capability_ids=tuple(sorted(set(capability_ids))),
        requires_approval=requires_approval,
    )
