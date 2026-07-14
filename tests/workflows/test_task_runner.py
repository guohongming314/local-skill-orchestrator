from __future__ import annotations

import json
from pathlib import Path

from vibe.compiler.context import CapabilityCandidate, ContextSource, SourceKind
from vibe.compiler.intent import TaskIntent
from vibe.models.risk import RiskLevel
from vibe.models.task import TaskPhase, TaskPlan, WorkflowMode
from vibe.workflows.scenarios import ScenarioId
from vibe.workflows.task_runner import (
    PhaseExecutionResult,
    TaskRunner,
    TaskRunStatus,
)


class ScriptedAppServer:
    def __init__(self, results: list[PhaseExecutionResult]) -> None:
        self.results = results
        self.prompts: list[str] = []
        self.started = 0
        self.resumed: list[str] = []

    async def start_thread(self, root: Path) -> str:
        self.started += 1
        return "thread-126"

    async def resume_thread(self, thread_id: str) -> str:
        self.resumed.append(thread_id)
        return thread_id

    async def execute_phase(self, thread_id: str, prompt: str) -> PhaseExecutionResult:
        assert thread_id == "thread-126"
        self.prompts.append(prompt)
        return self.results.pop(0)


def three_phase_plan() -> TaskPlan:
    return TaskPlan(
        task_id="task-126",
        intent="Ship the approved change",
        risk_level=RiskLevel.HIGH,
        workflow_mode=WorkflowMode.RIGOROUS,
        acceptance_criteria=("All phases complete.",),
        phases=(
            TaskPhase(
                phase_id="inspect",
                objective="Inspect.",
                completion_conditions=("Inspection complete.",),
                capability_ids=("cap.inspect",),
            ),
            TaskPhase(
                phase_id="approval",
                objective="Approve.",
                completion_conditions=("Approval recorded.",),
                capability_ids=("cap.approval",),
                requires_approval=True,
            ),
            TaskPhase(
                phase_id="implement",
                objective="Implement.",
                completion_conditions=("Implementation complete.",),
                capability_ids=("cap.implement",),
            ),
        ),
    )


def task_intent() -> TaskIntent:
    return TaskIntent(
        task_id="task-126",
        summary="Ship the approved change",
        scenario=ScenarioId.FEATURE,
        scope=("src/vibe/",),
        acceptance_criteria=("All phases complete.",),
    )


def candidates() -> tuple[CapabilityCandidate, ...]:
    return tuple(
        CapabilityCandidate(
            capability_id=f"cap.{phase}",
            provides=(f"{phase}-work",),
            phases=(phase,),
        )
        for phase in ("inspect", "approval", "implement")
    )


def sources() -> tuple[ContextSource, ...]:
    return (
        ContextSource(
            source_id="repository",
            digest="repository-digest",
            kind=SourceKind.REPOSITORY,
        ),
    )


def result(phase: str) -> PhaseExecutionResult:
    return PhaseExecutionResult(
        phase_id=phase,
        completed=True,
        completion_evidence=(f"{phase} done",),
        completion_conditions_met={
            "inspect": ("Inspection complete.",),
            "approval": ("Approval recorded.",),
            "implement": ("Implementation complete.",),
        }[phase],
        confirmed_facts=(f"confirmed:{phase}",),
    )


def test_three_phase_fixture_task_runs_to_completion_with_one_gate(tmp_path: Path) -> None:
    app_server = ScriptedAppServer([result("inspect"), result("approval"), result("implement")])
    approvals: list[str] = []

    def approve_phase(phase: TaskPhase) -> bool:
        approvals.append(phase.phase_id)
        return True

    runner = TaskRunner(
        root=tmp_path,
        app_server=app_server,
        checkpoint_path=tmp_path / "task-checkpoint.json",
        head_provider=lambda: "head-1",
        blueprint_digest_provider=lambda: "blueprint-1",
        approval_provider=approve_phase,
    )

    checkpoint = runner.run(
        task_intent(),
        three_phase_plan(),
        candidates=candidates(),
        sources=sources(),
        user_scope_digest="scope-1",
    )

    assert checkpoint.status is TaskRunStatus.COMPLETED
    assert checkpoint.completed_phase_ids == ("inspect", "approval", "implement")
    assert approvals == ["approval"]
    assert app_server.started == 1
    assert len(app_server.prompts) == 3
    for prompt, own_capability, other_capabilities in (
        (app_server.prompts[0], "cap.inspect", ("cap.approval", "cap.implement")),
        (app_server.prompts[1], "cap.approval", ("cap.inspect", "cap.implement")),
        (app_server.prompts[2], "cap.implement", ("cap.inspect", "cap.approval")),
    ):
        payload = json.loads(prompt)
        assert payload["context_capsule"]["selected_capability_ids"] == [own_capability]
        assert all(other not in payload["capability_content"] for other in other_capabilities)
    assert json.loads(app_server.prompts[1])["confirmed_state"] == ["confirmed:inspect"]
    assert json.loads(app_server.prompts[2])["confirmed_state"] == [
        "confirmed:inspect",
        "confirmed:approval",
    ]


def test_gate_refusal_halts_before_gated_phase_and_is_resumable(tmp_path: Path) -> None:
    app_server = ScriptedAppServer([result("inspect"), result("approval"), result("implement")])
    checkpoint_path = tmp_path / "task-checkpoint.json"
    runner = TaskRunner(
        root=tmp_path,
        app_server=app_server,
        checkpoint_path=checkpoint_path,
        head_provider=lambda: "head-1",
        blueprint_digest_provider=lambda: "blueprint-1",
        approval_provider=lambda _phase: False,
    )

    paused = runner.run(
        task_intent(),
        three_phase_plan(),
        candidates=candidates(),
        sources=sources(),
        user_scope_digest="scope-1",
    )

    assert paused.status is TaskRunStatus.AWAITING_APPROVAL
    assert paused.next_phase_id == "approval"
    assert paused.completed_phase_ids == ("inspect",)
    assert len(app_server.prompts) == 1

    resumed = TaskRunner(
        root=tmp_path,
        app_server=app_server,
        checkpoint_path=checkpoint_path,
        head_provider=lambda: "head-1",
        blueprint_digest_provider=lambda: "blueprint-1",
        approval_provider=lambda _phase: True,
    ).run(
        task_intent(),
        three_phase_plan(),
        candidates=candidates(),
        sources=sources(),
        user_scope_digest="scope-1",
        resume=True,
    )

    assert resumed.status is TaskRunStatus.COMPLETED
    assert app_server.resumed == ["thread-126"]
    assert len(app_server.prompts) == 3


def test_head_change_mid_run_invalidates_and_pauses_resumably(tmp_path: Path) -> None:
    heads = iter(("head-1", "head-1", "head-2"))
    app_server = ScriptedAppServer([result("inspect"), result("approval"), result("implement")])
    checkpoint_path = tmp_path / "task-checkpoint.json"
    runner = TaskRunner(
        root=tmp_path,
        app_server=app_server,
        checkpoint_path=checkpoint_path,
        head_provider=lambda: next(heads),
        blueprint_digest_provider=lambda: "blueprint-1",
        approval_provider=lambda _phase: True,
    )

    paused = runner.run(
        task_intent(),
        three_phase_plan(),
        candidates=candidates(),
        sources=sources(),
        user_scope_digest="scope-1",
    )

    assert paused.status is TaskRunStatus.INVALIDATED
    assert paused.next_phase_id == "approval"
    assert paused.completed_phase_ids == ("inspect",)
    assert len(app_server.prompts) == 1

    resumed = TaskRunner(
        root=tmp_path,
        app_server=app_server,
        checkpoint_path=checkpoint_path,
        head_provider=lambda: "head-2",
        blueprint_digest_provider=lambda: "blueprint-1",
        approval_provider=lambda _phase: True,
    ).run(
        task_intent(),
        three_phase_plan(),
        candidates=candidates(),
        sources=sources(),
        user_scope_digest="scope-1",
        resume=True,
    )

    assert resumed.status is TaskRunStatus.COMPLETED
    assert resumed.source_head == "head-2"
    assert app_server.resumed == ["thread-126"]
