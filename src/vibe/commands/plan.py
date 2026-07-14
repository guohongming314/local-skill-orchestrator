"""Preview a deterministic task workflow and Context Capsule without execution."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import typer

from vibe.compiler.context import (
    CapabilityCandidate,
    ContextSource,
    SourceKind,
    compile_context_capsule,
)
from vibe.compiler.intent import TaskIntent
from vibe.inspect.repository import inspect_repository
from vibe.models.capsule import ContextCapsule
from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    ScopeLevel,
    TaskOperation,
)
from vibe.models.task import TaskPlan
from vibe.workflows.scenarios import ScenarioId, ScenarioRequest, classify_scenario
from vibe.workflows.task_graph import build_task_plan

_ROUTE_CANDIDATES = (
    CapabilityCandidate(
        capability_id="analysis.code-relationships",
        provides=("code-relationship-analysis",),
        phases=("inspect",),
    ),
    CapabilityCandidate(
        capability_id="automation.release",
        provides=("release-automation",),
        phases=("implement",),
    ),
)


def plan_command(
    task_id: Annotated[str, typer.Option("--task-id")],
    intent: Annotated[str, typer.Option("--intent")],
    scenario: Annotated[ScenarioId, typer.Option("--scenario")],
    scope: Annotated[list[str], typer.Option("--scope")],
    acceptance: Annotated[list[str], typer.Option("--acceptance")],
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    phase: Annotated[str, typer.Option("--phase")] = "inspect",
    cross_module: Annotated[bool, typer.Option("--cross-module")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    capsule_output: Annotated[
        Path | None,
        typer.Option("--capsule-output", dir_okay=False, resolve_path=True),
    ] = None,
) -> None:
    """Compile a reviewable plan and capsule; never execute the requested task."""
    root = (path or Path.cwd()).resolve()
    try:
        task_plan, capsule = _compile_review(
            root,
            task_id=task_id,
            summary=intent,
            scenario=scenario,
            scope=tuple(scope),
            acceptance=tuple(acceptance),
            phase=phase,
            cross_module=cross_module,
        )
        if capsule_output is not None:
            capsule_output.parent.mkdir(parents=True, exist_ok=True)
            capsule_output.write_text(
                capsule.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
    except (OSError, RuntimeError, ValueError) as error:
        typer.echo(f"planning failed: {type(error).__name__}: {error}", err=True)
        raise typer.Exit(2) from error

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "schema_version": "1",
                    "task_plan": task_plan.model_dump(mode="json"),
                    "context_capsule": capsule.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    _emit_human(task_plan, capsule)


def _compile_review(
    root: Path,
    *,
    task_id: str,
    summary: str,
    scenario: ScenarioId,
    scope: tuple[str, ...],
    acceptance: tuple[str, ...],
    phase: str,
    cross_module: bool,
) -> tuple[TaskPlan, ContextCapsule]:
    snapshot = inspect_repository(root)
    task_intent = TaskIntent(
        task_id=task_id,
        summary=summary,
        scenario=scenario,
        scope=scope,
        acceptance_criteria=acceptance,
        cross_module=cross_module,
    )
    classification = classify_scenario(
        ScenarioRequest(
            scenario=scenario,
            scope=(
                ScopeLevel.MULTI_COMPONENT
                if cross_module or len(task_intent.scope) > 1
                else ScopeLevel.LOCAL
            ),
            data_sensitivity=DataSensitivity.PUBLIC,
            reversibility=Reversibility.REVERSIBLE,
            operations=_operations_for(scenario),
        )
    )
    task_plan = build_task_plan(
        task_id,
        summary,
        classification,
        acceptance_criteria=task_intent.acceptance_criteria,
    )
    head = snapshot.head or f"source-{snapshot.source_digest}"
    user_scope_digest = sha256("\0".join(task_intent.scope).encode()).hexdigest()
    capsule = compile_context_capsule(
        task_intent,
        task_plan,
        phase=phase,
        candidates=_ROUTE_CANDIDATES,
        sources=(
            ContextSource(
                source_id="repository",
                digest=snapshot.source_digest,
                kind=SourceKind.REPOSITORY,
            ),
        ),
        head=head,
        user_scope_digest=user_scope_digest,
    )
    return task_plan, capsule


def _operations_for(scenario: ScenarioId) -> frozenset[TaskOperation]:
    if scenario in {ScenarioId.REVIEW, ScenarioId.EXPLORATION}:
        return frozenset({TaskOperation.READ_PROJECT})
    return frozenset({TaskOperation.WRITE_PROJECT})


def _emit_human(task_plan: TaskPlan, capsule: ContextCapsule) -> None:
    typer.echo(f"Task: {task_plan.task_id} — {task_plan.intent}")
    typer.echo(f"Risk: {task_plan.risk_level.value} (deterministic scenario signals)")
    typer.echo(f"Workflow: {task_plan.workflow_mode.value}")
    typer.echo("Phases:")
    for phase in task_plan.phases:
        typer.echo(f"  - {phase.phase_id}: {phase.objective}")
    typer.echo("Selected capabilities:")
    if capsule.selected_capability_ids:
        for capability_id in capsule.selected_capability_ids:
            typer.echo(f"  - {capability_id}: required by the current phase and task scope")
    else:
        typer.echo("  - none: no extra capability is required for the current phase")
    typer.echo("Excluded capabilities:")
    if capsule.rejected_capability_ids:
        for capability_id in capsule.rejected_capability_ids:
            typer.echo(f"  - {capability_id}: unrelated to the current phase or scope")
    else:
        typer.echo("  - none")
    typer.echo(f"Token budget: {capsule.token_budget}")
    typer.echo("Invalidation:")
    for condition in capsule.invalidation_conditions:
        typer.echo(f"  - {condition}")
    typer.echo("Execution: disabled (review only)")
