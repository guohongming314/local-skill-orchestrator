from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibe.routing.phase_exposure import (
    CapabilityToolBinding,
    GatewayPhaseExposure,
    HostExposure,
    PhaseExposureRequest,
)


class RecordingHostAdapter:
    def __init__(self) -> None:
        self.requests: list[PhaseExposureRequest] = []

    def expose(self, request: PhaseExposureRequest) -> HostExposure:
        self.requests.append(request)
        enabled = set(request.selected_server_ids)
        return HostExposure(
            thread_config={
                "mcp_servers": {
                    server_id: {"enabled": server_id in enabled}
                    for server_id in request.known_server_ids
                }
            },
            transition="handoff" if len(self.requests) > 1 else "start",
        )


def bindings() -> tuple[CapabilityToolBinding, ...]:
    return (
        CapabilityToolBinding(
            capability_id="mcp.codegraph",
            provides=("code-graph-analysis",),
            server_id="codegraph",
            tool_names=("codegraph_explore", "codegraph_search"),
        ),
        CapabilityToolBinding(
            capability_id="mcp.playwright",
            provides=("browser.validation",),
            server_id="playwright",
            tool_names=("browser_navigate", "browser_snapshot"),
        ),
    )


def test_two_phase_fixture_flips_gateway_allowlist_at_transition(tmp_path: Path) -> None:
    allowlist = tmp_path / "capsule-selection.json"
    adapter = RecordingHostAdapter()
    exposure = GatewayPhaseExposure(
        allowlist_path=allowlist,
        bindings=bindings(),
        host_adapter=adapter,
    )

    investigate = exposure.expose("investigate", ("code-graph-analysis",))
    assert json.loads(allowlist.read_text()) == {
        "allowed_tools": ["codegraph_explore", "codegraph_search"]
    }

    regression = exposure.expose("regression-test", ("browser.validation",))
    assert json.loads(allowlist.read_text()) == {
        "allowed_tools": ["browser_navigate", "browser_snapshot"]
    }
    assert "codegraph_explore" not in regression.allowed_tools
    assert investigate.exposure_digest != regression.exposure_digest
    assert adapter.requests[1].selected_server_ids == ("playwright",)
    assert adapter.requests[1].known_server_ids == ("codegraph", "playwright")
    assert regression.thread_config["mcp_servers"] == {
        "codegraph": {"enabled": False},
        "playwright": {"enabled": True},
    }
    assert regression.transition == "handoff"


def test_concrete_manifest_id_can_select_its_taxonomy_tools(tmp_path: Path) -> None:
    allowlist = tmp_path / "capsule-selection.json"
    exposure = GatewayPhaseExposure(allowlist_path=allowlist, bindings=bindings())

    selected = exposure.expose("validate", ("mcp.playwright",))

    assert selected.allowed_tools == ("browser_navigate", "browser_snapshot")


def test_task_runner_applies_exposure_before_each_phase_turn(tmp_path: Path) -> None:
    from vibe.compiler.context import CapabilityCandidate, ContextSource, SourceKind
    from vibe.compiler.intent import TaskIntent
    from vibe.models.risk import RiskLevel
    from vibe.models.task import TaskPhase, TaskPlan, WorkflowMode
    from vibe.workflows.scenarios import ScenarioId
    from vibe.workflows.task_runner import PhaseExecutionResult, TaskRunner

    allowlist = tmp_path / "capsule-selection.json"
    adapter = RecordingHostAdapter()
    exposure = GatewayPhaseExposure(
        allowlist_path=allowlist,
        bindings=bindings(),
        host_adapter=adapter,
    )

    class PhaseAppServer:
        def __init__(self) -> None:
            self.sessions: list[tuple[str | None, dict[str, object]]] = []
            self.allowlists_at_turn: list[tuple[str, ...]] = []

        async def start_thread(self, root: Path) -> str:
            raise AssertionError("hard routing must use a configured phase session")

        async def resume_thread(self, thread_id: str) -> str:
            raise AssertionError("hard routing must hand off at the phase boundary")

        async def start_phase_thread(
            self,
            root: Path,
            previous_thread_id: str | None,
            session_config: dict[str, object],
        ) -> str:
            self.sessions.append((previous_thread_id, session_config))
            return f"phase-thread-{len(self.sessions)}"

        async def execute_phase(self, thread_id: str, prompt: str) -> PhaseExecutionResult:
            payload = json.loads(allowlist.read_text())
            self.allowlists_at_turn.append(tuple(payload["allowed_tools"]))
            phase = json.loads(prompt)["context_capsule"]["current_phase"]
            return PhaseExecutionResult(
                phase_id=phase,
                completed=True,
                completion_conditions_met=(f"{phase} complete",),
                confirmed_facts=(f"confirmed:{phase}",),
            )

    app_server = PhaseAppServer()
    plan = TaskPlan(
        task_id="task-exposure",
        intent="Fix and verify",
        risk_level=RiskLevel.MEDIUM,
        workflow_mode=WorkflowMode.STANDARD,
        acceptance_criteria=("complete",),
        phases=(
            TaskPhase(
                phase_id="investigate",
                objective="Investigate",
                completion_conditions=("investigate complete",),
                capability_ids=("code-graph-analysis",),
            ),
            TaskPhase(
                phase_id="regression-test",
                objective="Verify",
                completion_conditions=("regression-test complete",),
                capability_ids=("browser.validation",),
            ),
        ),
    )
    intent = TaskIntent(
        task_id="task-exposure",
        summary="Fix and verify",
        scenario=ScenarioId.BUG,
        scope=("src/",),
        acceptance_criteria=("complete",),
    )
    candidates = (
        CapabilityCandidate(
            capability_id="code-graph-analysis",
            provides=("code-graph-analysis",),
            phases=("investigate",),
        ),
        CapabilityCandidate(
            capability_id="browser.validation",
            provides=("browser.validation",),
            phases=("regression-test",),
        ),
    )

    checkpoint = TaskRunner(
        root=tmp_path,
        app_server=app_server,
        checkpoint_path=tmp_path / "checkpoint.json",
        head_provider=lambda: "head",
        blueprint_digest_provider=lambda: "blueprint",
        approval_provider=lambda _phase: True,
        phase_exposure=exposure,
    ).run(
        intent,
        plan,
        candidates=candidates,
        sources=(ContextSource(source_id="repo", digest="digest-123", kind=SourceKind.REPOSITORY),),
        user_scope_digest="scope",
    )

    assert app_server.allowlists_at_turn == [
        ("codegraph_explore", "codegraph_search"),
        ("browser_navigate", "browser_snapshot"),
    ]
    assert app_server.sessions[0][0] is None
    assert app_server.sessions[1][0] == "phase-thread-1"
    assert checkpoint.codex_thread_id == "phase-thread-2"
    assert checkpoint.exposure_digest == adapter.requests[-1].exposure_digest


def test_task_runner_without_gateway_logs_one_soft_routing_notice(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from vibe.compiler.context import CapabilityCandidate, ContextSource, SourceKind
    from vibe.compiler.intent import TaskIntent
    from vibe.models.risk import RiskLevel
    from vibe.models.task import TaskPhase, TaskPlan, WorkflowMode
    from vibe.workflows.scenarios import ScenarioId
    from vibe.workflows.task_runner import PhaseExecutionResult, TaskRunner

    class SoftAppServer:
        def __init__(self) -> None:
            self.turns = 0

        async def start_thread(self, root: Path) -> str:
            return "soft-thread"

        async def resume_thread(self, thread_id: str) -> str:
            return thread_id

        async def execute_phase(self, thread_id: str, prompt: str) -> PhaseExecutionResult:
            self.turns += 1
            phase = json.loads(prompt)["context_capsule"]["current_phase"]
            return PhaseExecutionResult(
                phase_id=phase,
                completed=True,
                completion_conditions_met=(f"{phase} complete",),
            )

    phases = tuple(
        TaskPhase(
            phase_id=phase,
            objective=phase,
            completion_conditions=(f"{phase} complete",),
            capability_ids=(f"cap.{phase}",),
        )
        for phase in ("one", "two")
    )
    plan = TaskPlan(
        task_id="soft-task",
        intent="soft",
        risk_level=RiskLevel.LOW,
        workflow_mode=WorkflowMode.FAST,
        acceptance_criteria=("complete",),
        phases=phases,
    )
    intent = TaskIntent(
        task_id="soft-task",
        summary="soft",
        scenario=ScenarioId.DOCUMENTATION,
        scope=(".",),
        acceptance_criteria=("complete",),
    )
    candidates = tuple(
        CapabilityCandidate(capability_id=f"cap.{phase}", provides=(phase,), phases=(phase,))
        for phase in ("one", "two")
    )

    caplog.set_level(logging.WARNING)
    app_server = SoftAppServer()
    TaskRunner(
        root=tmp_path,
        app_server=app_server,
        checkpoint_path=tmp_path / "soft-checkpoint.json",
        head_provider=lambda: "head",
        blueprint_digest_provider=lambda: "blueprint",
        approval_provider=lambda _phase: True,
    ).run(
        intent,
        plan,
        candidates=candidates,
        sources=(ContextSource(source_id="repo", digest="digest-123", kind=SourceKind.REPOSITORY),),
        user_scope_digest="scope",
    )

    notices = [
        record.message
        for record in caplog.records
        if "hard tool isolation unavailable" in record.message
    ]
    assert app_server.turns == 2
    assert notices == [
        "Hard routing gateway is not configured; hard tool isolation unavailable, "
        "using soft routing."
    ]


def test_binding_uses_capability_manifest_provides_for_abstract_mapping(tmp_path: Path) -> None:
    from vibe.models.capability import (
        CapabilityKind,
        CapabilityManifest,
        CapabilityScope,
    )

    manifest = CapabilityManifest(
        capability_id="mcp.playwright",
        name="Playwright MCP",
        kind=CapabilityKind.MCP,
        scope=CapabilityScope.USER,
        source="config.toml#mcp_servers.playwright",
        provides=("browser.validation",),
        content_digest="12345678",
    )
    binding = CapabilityToolBinding.from_manifest(
        manifest,
        server_id="playwright",
        tool_names=("browser_snapshot",),
    )
    exposure = GatewayPhaseExposure(
        allowlist_path=tmp_path / "selection.json",
        bindings=(binding,),
    )

    selected = exposure.expose("verify", ("browser.validation",))

    assert selected.allowed_tools == ("browser_snapshot",)
