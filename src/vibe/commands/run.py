"""Execute a natural-language task through a phase-gated Codex thread."""

from __future__ import annotations

import json
import shlex
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import typer

from vibe.codex.app_server import CodexAppServerClient, agent_message_text
from vibe.codex.jsonrpc import JsonRpcSubprocessClient
from vibe.commands.explain_task import CodexScenarioClassification, _scenario_request
from vibe.commands.plan import _ROUTE_CANDIDATES, _context_sources
from vibe.compiler.intent import TaskIntent
from vibe.inspect.repository import inspect_repository
from vibe.models.risk import RiskLevel
from vibe.models.task import TaskPlan, WorkflowMode
from vibe.workflows.scenarios import ScenarioClassification, classify_scenario
from vibe.workflows.task_graph import build_task_plan
from vibe.workflows.task_runner import (
    PhaseExecutionResult,
    TaskRunCheckpoint,
    TaskRunner,
)

_LEVEL_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}
_ACTIVE_PLAN_PHASES: dict[str, tuple[str, ...]] = {}


class CodexTaskAppServer:
    """Adapt the reusable app-server lifecycle to structured task phase execution."""

    def __init__(self, command: tuple[str, ...]) -> None:
        self.transport = JsonRpcSubprocessClient(command)
        self.client = CodexAppServerClient(self.transport)
        self.started = False

    async def _start(self) -> None:
        if not self.started:
            await self.transport.start()
            await self.client.initialize()
            self.started = True

    async def start_thread(self, root: Path) -> str:
        await self._start()
        return (await self.client.start_thread(cwd=root)).id

    async def resume_thread(self, thread_id: str) -> str:
        await self._start()
        return (await self.client.resume_thread(thread_id)).id

    async def execute_phase(self, thread_id: str, prompt: str) -> PhaseExecutionResult:
        result = await self.client.run_turn(
            thread_id,
            prompt,
            output_schema=PhaseExecutionResult.model_json_schema(),
        )
        return PhaseExecutionResult.model_validate_json(agent_message_text(result))

    async def close(self) -> None:
        if self.started:
            await self.transport.close()
            self.started = False


def run_command(
    plan_ref: Annotated[
        str, typer.Argument(help="Natural-language task or approved plan reference.")
    ],
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    scope: Annotated[list[str] | None, typer.Option("--scope")] = None,
    acceptance: Annotated[list[str] | None, typer.Option("--acceptance")] = None,
    checkpoint: Annotated[
        Path | None, typer.Option("--checkpoint", dir_okay=False, resolve_path=True)
    ] = None,
    resume: Annotated[bool, typer.Option("--resume")] = False,
    approve: Annotated[bool, typer.Option("--yes", help="Approve every plan gate.")] = False,
    scenario: Annotated[
        str | None, typer.Option("--scenario", help="Explicit scenario override.")
    ] = None,
    app_server_command: Annotated[
        str, typer.Option("--app-server-command", hidden=True)
    ] = "codex app-server",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run a plan sequentially; pause durably at gates or invalidation boundaries."""
    root = (path or Path.cwd()).resolve()
    checkpoint_path = checkpoint or root / ".vibe-task-checkpoint.json"
    task_scope = tuple(scope or ["."])
    task_acceptance = tuple(acceptance or ["Requested task outcome is verified."])
    try:
        from vibe.workflows.scenarios import ScenarioId

        override = ScenarioId(scenario) if scenario is not None else None
        request, model_result = _scenario_request(plan_ref, root, override)
        classification = _validated_classification(classify_scenario(request), model_result)
        task_id = f"run-{sha256(plan_ref.encode()).hexdigest()[:12]}"
        intent = TaskIntent(
            task_id=task_id,
            summary=plan_ref,
            scenario=classification.scenario,
            scope=task_scope,
            acceptance_criteria=task_acceptance,
            cross_module=len(task_scope) > 1,
        )
        plan = build_task_plan(
            task_id,
            plan_ref,
            classification,
            acceptance_criteria=task_acceptance,
        )
        global _ACTIVE_PLAN_PHASES
        _ACTIVE_PLAN_PHASES = {phase.phase_id: phase.completion_conditions for phase in plan.phases}
        snapshot = inspect_repository(root)
        sources = _context_sources(root, snapshot.source_digest)
        runner = TaskRunner(
            root=root,
            app_server=_build_app_server(tuple(shlex.split(app_server_command))),
            checkpoint_path=checkpoint_path,
            head_provider=lambda: _repository_head(root),
            blueprint_digest_provider=lambda: _blueprint_digest(root),
            approval_provider=(
                lambda phase: approve or typer.confirm(f"Approve phase {phase.phase_id}?")
            ),
        )
        result = runner.run(
            intent,
            plan,
            candidates=_ROUTE_CANDIDATES,
            sources=sources,
            user_scope_digest=sha256("\0".join(intent.scope).encode()).hexdigest(),
            resume=resume,
        )
    except typer.Exit:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        typer.echo(f"run failed: {type(error).__name__}: {error}", err=True)
        raise typer.Exit(2) from error

    _emit(result, plan, json_output=json_output)


def _validated_classification(
    deterministic: ScenarioClassification,
    model_result: CodexScenarioClassification | None,
) -> ScenarioClassification:
    if (
        model_result is None
        or _LEVEL_ORDER[model_result.risk_level] <= _LEVEL_ORDER[deterministic.risk.level]
    ):
        return deterministic
    raised_level = model_result.risk_level
    risk = deterministic.risk.model_copy(
        update={
            "level": raised_level,
            "requires_approval": (
                deterministic.risk.requires_approval
                or _LEVEL_ORDER[raised_level] >= _LEVEL_ORDER[RiskLevel.HIGH]
            ),
        }
    )
    workflow = (
        WorkflowMode.RIGOROUS
        if _LEVEL_ORDER[raised_level] >= _LEVEL_ORDER[RiskLevel.HIGH]
        else WorkflowMode.STANDARD
    )
    return replace(
        deterministic,
        risk=risk,
        workflow_mode=workflow,
        explanation=(*deterministic.explanation, "Codex raised the validated risk level."),
    )


def _build_app_server(command: tuple[str, ...]) -> CodexTaskAppServer:
    return CodexTaskAppServer(command)


def _repository_head(root: Path) -> str:
    snapshot = inspect_repository(root)
    return snapshot.head or "git:none"


def _blueprint_digest(root: Path) -> str:
    blueprint = root / ".ai-project" / "blueprint.json"
    if not blueprint.is_file():
        return "blueprint:none"
    return sha256(blueprint.read_bytes()).hexdigest()


def _emit(result: TaskRunCheckpoint, plan: TaskPlan, *, json_output: bool) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                {
                    **result.model_dump(mode="json"),
                    "risk_level": plan.risk_level.value,
                    "workflow_mode": plan.workflow_mode.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    typer.echo(f"Task run: {result.status.value}")
    typer.echo(f"Risk: {plan.risk_level.value}")
    typer.echo(f"Workflow: {plan.workflow_mode.value}")
    typer.echo(f"Completed phases: {', '.join(result.completed_phase_ids) or 'none'}")
    if result.next_phase_id is not None:
        typer.echo(f"Next phase: {result.next_phase_id}")
    typer.echo(f"Checkpoint: {result.task_id}")
