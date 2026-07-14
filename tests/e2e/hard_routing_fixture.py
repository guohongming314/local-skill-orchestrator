from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from vibe.compiler.context import CapabilityCandidate, ContextSource, SourceKind
from vibe.compiler.intent import TaskIntent
from vibe.models.risk import RiskLevel
from vibe.models.task import TaskPhase, TaskPlan, WorkflowMode
from vibe.routing.allowlist import AllowlistFile
from vibe.routing.gateway import GatewayAuditEvent, McpGateway
from vibe.routing.phase_exposure import (
    CapabilityToolBinding,
    GatewayPhaseExposure,
    HostExposure,
    PhaseExposureRequest,
)
from vibe.workflows.scenarios import ScenarioId
from vibe.workflows.task_runner import PhaseExecutionResult, TaskRunCheckpoint, TaskRunner

_INVESTIGATE_TOOLS = ("codegraph_explore", "repository_search")
_REGRESSION_TOOLS = ("browser_snapshot", "browser_validate")
_ALL_TOOLS = _INVESTIGATE_TOOLS + _REGRESSION_TOOLS


def _fake_upstream() -> Server[object]:
    server: Server[object] = Server("hard-routing-e2e-upstream")

    @server.list_tools()  # type: ignore[untyped-decorator,no-untyped-call]
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=name,
                description=f"Fake {name} tool",
                inputSchema={"type": "object"},
            )
            for name in _ALL_TOOLS
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, object]) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text=f"called {name}")],
            isError=False,
        )

    return server


@asynccontextmanager
async def _connected_session(server: Server[object]) -> AsyncIterator[ClientSession]:
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream(10)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream(10)

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(
            server.run,
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )
        async with ClientSession(server_to_client_receive, client_to_server_send) as session:
            await session.initialize()
            yield session
        tasks.cancel_scope.cancel()


def _write_allowlist(path: Path, tools: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"allowed_tools": list(tools)}), encoding="utf-8")


class _ExplicitHostAdapter:
    def expose(self, request: PhaseExposureRequest) -> HostExposure:
        selected = set(request.selected_server_ids)
        return HostExposure(
            thread_config={
                "mcp_servers": {
                    server_id: {"enabled": server_id in selected}
                    for server_id in request.known_server_ids
                }
            },
            transition="handoff",
        )


class _VisibilityAppServer:
    def __init__(
        self,
        *,
        allowlist_path: Path,
        gateway_enabled: bool,
        visible_tools_by_phase: dict[str, tuple[str, ...]],
        audit_events: list[GatewayAuditEvent],
    ) -> None:
        self.allowlist_path = allowlist_path
        self.gateway_enabled = gateway_enabled
        self.visible_tools_by_phase = visible_tools_by_phase
        self.audit_events = audit_events
        self._stack: AsyncExitStack | None = None
        self._client: ClientSession | None = None
        self._thread_count = 0

    async def start_thread(self, root: Path) -> str:
        return self._new_thread_id()

    async def resume_thread(self, thread_id: str) -> str:
        return thread_id

    async def start_phase_thread(
        self,
        root: Path,
        previous_thread_id: str | None,
        session_config: dict[str, object],
    ) -> str:
        return self._new_thread_id()

    async def execute_phase(self, thread_id: str, prompt: str) -> PhaseExecutionResult:
        client = await self._session()
        phase = str(json.loads(prompt)["context_capsule"]["current_phase"])
        tools = await client.list_tools()
        self.visible_tools_by_phase[phase] = tuple(tool.name for tool in tools.tools)

        if self.gateway_enabled:
            blocked_tool = (
                "browser_validate" if phase == "investigate" else "codegraph_explore"
            )
            blocked = await client.call_tool(blocked_tool, {})
            if blocked.isError is not True:
                raise AssertionError(f"gateway unexpectedly allowed {blocked_tool}")

        return PhaseExecutionResult(
            phase_id=phase,
            completed=True,
            completion_conditions_met=(f"{phase} complete",),
            confirmed_facts=(f"confirmed:{phase}",),
        )

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._client = None

    async def _session(self) -> ClientSession:
        if self._client is not None:
            return self._client
        self._stack = AsyncExitStack()
        upstream = await self._stack.enter_async_context(_connected_session(_fake_upstream()))
        if self.gateway_enabled:
            gateway = McpGateway(
                upstream,
                AllowlistFile(self.allowlist_path),
                self.audit_events.append,
            )
            self._client = await self._stack.enter_async_context(
                _connected_session(gateway.server)
            )
        else:
            self._client = upstream
        return self._client

    def _new_thread_id(self) -> str:
        self._thread_count += 1
        return f"phase-thread-{self._thread_count}"


class HardRoutingTaskFixture:
    """Acceptance fixture for hard-routed and soft-routed bug-fix task runs."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.visible_tools_by_phase: dict[str, tuple[str, ...]] = {}
        self._audit_events: list[GatewayAuditEvent] = []

    @property
    def all_tool_names(self) -> tuple[str, ...]:
        return _ALL_TOOLS

    @property
    def audit_events(self) -> list[tuple[str, str]]:
        return [(event.tool_name, event.reason) for event in self._audit_events]

    def run(self, *, gateway_enabled: bool) -> TaskRunCheckpoint:
        self.visible_tools_by_phase.clear()
        self._audit_events.clear()
        allowlist_path = self.root / "gateway-allowlist.json"
        app_server = _VisibilityAppServer(
            allowlist_path=allowlist_path,
            gateway_enabled=gateway_enabled,
            visible_tools_by_phase=self.visible_tools_by_phase,
            audit_events=self._audit_events,
        )
        phase_exposure = None
        if gateway_enabled:
            phase_exposure = GatewayPhaseExposure(
                allowlist_path=allowlist_path,
                bindings=(
                    CapabilityToolBinding(
                        capability_id="code-investigation",
                        provides=("code-investigation",),
                        server_id="investigation-upstream",
                        tool_names=_INVESTIGATE_TOOLS,
                    ),
                    CapabilityToolBinding(
                        capability_id="browser-regression",
                        provides=("browser-regression",),
                        server_id="regression-upstream",
                        tool_names=_REGRESSION_TOOLS,
                    ),
                ),
                host_adapter=_ExplicitHostAdapter(),
            )

        intent, plan, candidates = self._task()
        return TaskRunner(
            root=self.root,
            app_server=app_server,
            checkpoint_path=self.root / "hard-routing-checkpoint.json",
            head_provider=lambda: "head-1",
            blueprint_digest_provider=lambda: "blueprint-1",
            approval_provider=lambda _phase: True,
            phase_exposure=phase_exposure,
        ).run(
            intent,
            plan,
            candidates=candidates,
            sources=(
                ContextSource(
                    source_id="fixture-repository",
                    digest="fixture-digest",
                    kind=SourceKind.REPOSITORY,
                ),
            ),
            user_scope_digest="fixture-scope",
        )

    async def concurrent_disjoint_inventories(self) -> dict[str, tuple[str, ...]]:
        investigate_allowlist = self.root / "investigate-allowlist.json"
        regression_allowlist = self.root / "regression-allowlist.json"
        _write_allowlist(investigate_allowlist, _INVESTIGATE_TOOLS)
        _write_allowlist(regression_allowlist, _REGRESSION_TOOLS)
        inventories: dict[str, tuple[str, ...]] = {}

        async with AsyncExitStack() as stack:
            investigate_upstream = await stack.enter_async_context(
                _connected_session(_fake_upstream())
            )
            regression_upstream = await stack.enter_async_context(
                _connected_session(_fake_upstream())
            )
            investigate_client = await stack.enter_async_context(
                _connected_session(
                    McpGateway(
                        investigate_upstream, AllowlistFile(investigate_allowlist)
                    ).server
                )
            )
            regression_client = await stack.enter_async_context(
                _connected_session(
                    McpGateway(
                        regression_upstream, AllowlistFile(regression_allowlist)
                    ).server
                )
            )

            async def capture(name: str, client: ClientSession) -> None:
                result = await client.list_tools()
                inventories[name] = tuple(tool.name for tool in result.tools)

            async with anyio.create_task_group() as tasks:
                tasks.start_soon(capture, "investigate-thread", investigate_client)
                tasks.start_soon(capture, "regression-thread", regression_client)

        return inventories

    @staticmethod
    def _task() -> tuple[TaskIntent, TaskPlan, tuple[CapabilityCandidate, ...]]:
        phases = (
            TaskPhase(
                phase_id="investigate",
                objective="Investigate the bug",
                completion_conditions=("investigate complete",),
                capability_ids=("code-investigation",),
            ),
            TaskPhase(
                phase_id="regression-test",
                objective="Run browser regression checks",
                completion_conditions=("regression-test complete",),
                capability_ids=("browser-regression",),
            ),
        )
        intent = TaskIntent(
            task_id="hard-routing-bug-fix",
            summary="Fix a checkout regression",
            scenario=ScenarioId.BUG,
            scope=("src/checkout.py",),
            acceptance_criteria=("The regression is fixed and verified.",),
        )
        plan = TaskPlan(
            task_id=intent.task_id,
            intent=intent.summary,
            risk_level=RiskLevel.MEDIUM,
            workflow_mode=WorkflowMode.STANDARD,
            acceptance_criteria=intent.acceptance_criteria,
            phases=phases,
        )
        candidates = (
            CapabilityCandidate(
                capability_id="code-investigation",
                provides=("code-investigation",),
                phases=("investigate",),
            ),
            CapabilityCandidate(
                capability_id="browser-regression",
                provides=("browser-regression",),
                phases=("regression-test",),
            ),
        )
        return intent, plan, candidates
