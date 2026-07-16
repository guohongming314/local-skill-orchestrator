"""Preview a deterministic task workflow and Context Capsule without execution."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import typer
from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from vibe.compiler.context import (
    CapabilityCandidate,
    ContextSource,
    SourceKind,
    compile_context_capsule,
)
from vibe.compiler.intent import TaskIntent
from vibe.inspect.repository import inspect_repository
from vibe.models.capability import Permission
from vibe.models.capsule import ContextCapsule
from vibe.models.outcome import TaskOutcome
from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    ScopeLevel,
    TaskOperation,
)
from vibe.models.task import TaskPlan
from vibe.persistence.database import create_sqlite_engine, default_database_path, migration_config
from vibe.persistence.repositories import TaskOutcomeRepository
from vibe.workflows.scenarios import ScenarioId, ScenarioRequest, classify_scenario
from vibe.workflows.task_graph import build_task_plan

_ROUTE_CANDIDATES = (
    CapabilityCandidate(
        capability_id="analysis.code-relationships",
        provides=("code-relationship-analysis",),
        phases=("inspect",),
        permissions=frozenset({Permission.READ_PROJECT}),
    ),
    CapabilityCandidate(
        capability_id="automation.release",
        provides=("release-automation",),
        phases=("implement",),
        permissions=frozenset({Permission.EXECUTE_COMMAND, Permission.NETWORK}),
    ),
)
_DEPRECATION_WARNING = (
    "Warning: 'vibe plan' is deprecated and retained for compatibility and diagnostic "
    "use only. Native Skill selection is the normal Codex workflow."
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
    record_outcome: Annotated[bool, typer.Option("--record-outcome")] = False,
    capability_used: Annotated[list[str] | None, typer.Option("--capability-used")] = None,
    verification_passed: Annotated[
        bool, typer.Option("--verification-passed/--verification-failed")
    ] = True,
    user_rework: Annotated[bool, typer.Option("--user-rework")] = False,
    database: Annotated[Path | None, typer.Option("--database", hidden=True)] = None,
) -> None:
    """Compatibility and diagnostic plan preview; never execute the task.

    Native Skill selection in the current Codex conversation is the normal workflow.
    """
    typer.echo(_DEPRECATION_WARNING, err=True)
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
        if record_outcome:
            used = tuple(sorted(set(capability_used or ())))
            recommended = {
                capability_id
                for task_phase in task_plan.phases
                for capability_id in task_phase.capability_ids
            }
            _outcome_repository(database).record(
                task_id,
                TaskOutcome(
                    task_type=scenario.value,
                    workflow=task_plan.workflow_mode.value,
                    capabilities_used=used,
                    verification_passed=verification_passed,
                    user_rework=user_rework,
                    unused_recommendations=tuple(sorted(recommended - set(used))),
                ),
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
        sources=_context_sources(root, snapshot.source_digest),
        head=head,
        user_scope_digest=user_scope_digest,
    )
    return task_plan, capsule


def _operations_for(scenario: ScenarioId) -> frozenset[TaskOperation]:
    specialized = {
        ScenarioId.SECURITY: TaskOperation.MODIFY_SECURITY,
        ScenarioId.MIGRATION: TaskOperation.MIGRATE_DATA,
        ScenarioId.RELEASE: TaskOperation.DEPLOY,
    }
    if scenario in {ScenarioId.REVIEW, ScenarioId.EXPLORATION}:
        return frozenset({TaskOperation.READ_PROJECT})
    return frozenset({specialized.get(scenario, TaskOperation.WRITE_PROJECT)})


def _context_sources(root: Path, repository_digest: str) -> tuple[ContextSource, ...]:
    sources = [
        ContextSource(
            source_id="repository",
            digest=repository_digest,
            kind=SourceKind.REPOSITORY,
        )
    ]
    marker = root / ".memory-provider.json"
    if marker.is_file():
        payload = json.loads(marker.read_text(encoding="utf-8-sig"))
        provider = payload.get("provider")
        mode = payload.get("mode")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("memory provider marker requires a non-empty provider")
        if mode != "lead-only":
            raise ValueError("memory provider must use lead-only mode")
        sources.append(
            ContextSource(
                source_id=f"memory:{provider.strip()}",
                digest=sha256(marker.read_bytes()).hexdigest(),
                kind=SourceKind.MEMORY,
            )
        )
    return tuple(sorted(sources, key=lambda item: item.source_id))


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
    typer.echo("Requested permissions:")
    if capsule.requested_permissions:
        for permission in capsule.requested_permissions:
            typer.echo(f"  - {permission.value}")
    else:
        typer.echo("  - none")
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


def _outcome_repository(database: Path | None) -> TaskOutcomeRepository:
    database_path = database or default_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(migration_config(database_path), "head")
    factory = sessionmaker(
        create_sqlite_engine(database_path), class_=Session, expire_on_commit=False
    )
    return TaskOutcomeRepository(factory)
