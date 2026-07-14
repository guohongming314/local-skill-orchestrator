"""Explain task routing and capability decisions without executing the task."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

import anyio
import typer
from pydantic import BaseModel, ConfigDict

from vibe.codex.exec_fallback import CodexExecFallback
from vibe.commands.plan import _ROUTE_CANDIDATES, _context_sources, _operations_for
from vibe.compiler.context import compile_context_capsule
from vibe.compiler.intent import TaskIntent
from vibe.inspect.repository import inspect_repository
from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    RiskLevel,
    ScopeLevel,
    TaskOperation,
)
from vibe.models.task import WorkflowMode
from vibe.workflows.scenarios import (
    ScenarioClassification,
    ScenarioId,
    ScenarioRequest,
    classify_scenario,
)
from vibe.workflows.task_graph import build_task_plan


class CodexScenarioClassification(BaseModel):
    """Structured intent and signal classification requested from Codex."""

    model_config = ConfigDict(frozen=True)

    scenario: ScenarioId
    scope: ScopeLevel
    data_sensitivity: DataSensitivity
    reversibility: Reversibility
    operations: frozenset[TaskOperation]
    risk_level: RiskLevel
    workflow_mode: WorkflowMode


class CapabilityDecision(BaseModel):
    """One explainable capability routing decision."""

    model_config = ConfigDict(frozen=True)

    capability_id: str
    reason: str


class PhaseExplanation(BaseModel):
    """Capability bindings and reasons for one workflow phase."""

    model_config = ConfigDict(frozen=True)

    phase_id: str
    selected: tuple[CapabilityDecision, ...] = ()
    deferred: tuple[CapabilityDecision, ...] = ()
    rejected: tuple[CapabilityDecision, ...] = ()


class TaskExplanation(BaseModel):
    """Published JSON schema for ``vibe explain-task --json``."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1"] = "1"
    task: str
    scenario: ScenarioId
    risk_level: RiskLevel
    workflow_mode: WorkflowMode
    classification_reasons: tuple[str, ...]
    phases: tuple[PhaseExplanation, ...]
    execution: Literal["disabled"] = "disabled"


def explain_task_command(
    task: Annotated[str, typer.Argument(help="Natural-language task description.")],
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    scenario: Annotated[
        ScenarioId | None,
        typer.Option("--scenario", help="Explicitly override Codex intent classification."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Explain classification, workflow, and phase bindings without execution."""
    root = (path or Path.cwd()).resolve()
    try:
        request, codex_result = _scenario_request(task, root, scenario)
        classification = classify_scenario(request)
        if codex_result is not None and _disagrees(codex_result, classification):
            typer.echo(
                "Codex classification disagrees with deterministic risk signals: "
                f"Codex proposed {codex_result.risk_level.value}/"
                f"{codex_result.workflow_mode.value}; deterministic validation produced "
                f"{classification.risk.level.value}/"
                f"{classification.workflow_mode.value}."
            )
            if not typer.confirm("Use the deterministic validated classification?"):
                raise typer.Exit(2)
        explanation = _build_explanation(root, task, classification, request.operations)
    except typer.Exit:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        typer.echo(f"explanation failed: {type(error).__name__}: {error}", err=True)
        raise typer.Exit(2) from error

    if json_output:
        typer.echo(
            json.dumps(
                explanation.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    _emit_human(explanation)


def _scenario_request(
    task: str,
    root: Path,
    override: ScenarioId | None,
) -> tuple[ScenarioRequest, CodexScenarioClassification | None]:
    if override is not None:
        return (
            ScenarioRequest(
                scenario=override,
                scope=ScopeLevel.LOCAL,
                data_sensitivity=DataSensitivity.PUBLIC,
                reversibility=Reversibility.REVERSIBLE,
                operations=_operations_for(override),
            ),
            None,
        )
    result = _classify_with_codex(task, root)
    return (
        ScenarioRequest(
            scenario=result.scenario,
            scope=result.scope,
            data_sensitivity=result.data_sensitivity,
            reversibility=result.reversibility,
            operations=result.operations,
        ),
        result,
    )


def _classify_with_codex(task: str, root: Path) -> CodexScenarioClassification:
    prompt = (
        "Classify this software-engineering task. Return only the requested structured "
        "result. Infer scenario and explicit deterministic risk signals; then predict the "
        "risk level and workflow mode those signals imply. Task: "
        f"{task}"
    )

    async def run() -> CodexScenarioClassification:
        return await CodexExecFallback().run(
            prompt=prompt,
            model_type=CodexScenarioClassification,
            cwd=root,
        )

    return anyio.run(run)


def _disagrees(
    codex_result: CodexScenarioClassification,
    deterministic: ScenarioClassification,
) -> bool:
    return (
        codex_result.risk_level is not deterministic.risk.level
        or codex_result.workflow_mode is not deterministic.workflow_mode
    )


def _build_explanation(
    root: Path,
    task: str,
    classification: ScenarioClassification,
    operations: frozenset[TaskOperation],
) -> TaskExplanation:
    snapshot = inspect_repository(root)
    task_id = f"explain-{sha256(task.encode()).hexdigest()[:12]}"
    intent = TaskIntent(
        task_id=task_id,
        summary=task,
        scenario=classification.scenario,
        scope=(".",),
        acceptance_criteria=("Requested task outcome is verified.",),
    )
    plan = build_task_plan(
        task_id,
        task,
        classification,
        acceptance_criteria=intent.acceptance_criteria,
    )
    head = snapshot.head or f"source-{snapshot.source_digest}"
    source = _context_sources(root, snapshot.source_digest)
    phase_ids = [phase.phase_id for phase in plan.phases]
    if _needs_security_review(classification.scenario, operations):
        phase_ids.insert(phase_ids.index("review"), "security-review")

    explanations: list[PhaseExplanation] = []
    for phase_id in phase_ids:
        if phase_id == "security-review":
            explanations.append(
                PhaseExplanation(
                    phase_id=phase_id,
                    selected=(
                        CapabilityDecision(
                            capability_id="review.security",
                            reason=(
                                "Payment or security-sensitive work requires "
                                "focused security review."
                            ),
                        ),
                    ),
                    rejected=tuple(
                        CapabilityDecision(
                            capability_id=candidate.capability_id,
                            reason="The capability is not applicable to the security-review phase.",
                        )
                        for candidate in _ROUTE_CANDIDATES
                    ),
                )
            )
            continue
        capsule = compile_context_capsule(
            intent,
            plan,
            phase=phase_id,
            candidates=_ROUTE_CANDIDATES,
            sources=source,
            head=head,
            user_scope_digest=sha256(b"").hexdigest(),
        )
        security_review_index = (
            phase_ids.index("security-review") if "security-review" in phase_ids else None
        )
        current_index = phase_ids.index(phase_id)
        security_deferred = (
            security_review_index is not None and current_index < security_review_index
        )
        security_decision = CapabilityDecision(
            capability_id="review.security",
            reason=(
                "Deferred until the dedicated security-review phase."
                if security_deferred
                else f"Rejected because it is not needed in the {phase_id} phase."
            ),
        )
        explanations.append(
            PhaseExplanation(
                phase_id=phase_id,
                selected=tuple(
                    CapabilityDecision(
                        capability_id=capability_id,
                        reason=f"Selected because it is required for the {phase_id} phase.",
                    )
                    for capability_id in capsule.selected_capability_ids
                ),
                deferred=(security_decision,) if security_deferred else (),
                rejected=(
                    *(
                        CapabilityDecision(
                            capability_id=capability_id,
                            reason=f"Rejected because it is not needed in the {phase_id} phase.",
                        )
                        for capability_id in capsule.rejected_capability_ids
                    ),
                    *((security_decision,) if not security_deferred else ()),
                ),
            )
        )
    return TaskExplanation(
        task=task,
        scenario=classification.scenario,
        risk_level=classification.risk.level,
        workflow_mode=classification.workflow_mode,
        classification_reasons=classification.explanation,
        phases=tuple(explanations),
    )


def _needs_security_review(
    scenario: ScenarioId, operations: frozenset[TaskOperation]
) -> bool:
    return scenario is ScenarioId.SECURITY or bool(
        operations & {TaskOperation.HANDLE_PAYMENT, TaskOperation.MODIFY_SECURITY}
    )


def _emit_human(explanation: TaskExplanation) -> None:
    typer.echo(f"Task: {explanation.task}")
    typer.echo(f"Scenario: {explanation.scenario.value}")
    typer.echo(f"Risk: {explanation.risk_level.value}")
    typer.echo(f"Workflow: {explanation.workflow_mode.value}")
    typer.echo("Classification reasons:")
    for reason in explanation.classification_reasons:
        typer.echo(f"  - {reason}")
    for phase in explanation.phases:
        typer.echo(f"Phase: {phase.phase_id}")
        for label, decisions in (
            ("Selected", phase.selected),
            ("Deferred", phase.deferred),
            ("Rejected", phase.rejected),
        ):
            typer.echo(f"  {label} capabilities:")
            if not decisions:
                typer.echo("    - none")
            for decision in decisions:
                typer.echo(f"    - {decision.capability_id}: {decision.reason}")
    typer.echo("Execution: disabled")
