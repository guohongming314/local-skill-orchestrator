from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from vibe.routing.allowlist import AllowlistFile
from vibe.routing.gateway import GatewayAuditEvent, McpGateway


def fake_upstream() -> Server[object]:
    server: Server[object] = Server("fake-upstream")

    @server.list_tools()  # type: ignore[untyped-decorator,no-untyped-call]
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=f"tool-{index}",
                description=f"Fake tool {index}",
                inputSchema={"type": "object"},
            )
            for index in range(10)
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, object]) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text=f"called {name}")],
            isError=False,
        )

    return server


@asynccontextmanager
async def connected_session(server: Server[object]) -> AsyncIterator[ClientSession]:
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


def write_allowlist(path: Path, *tool_names: str) -> None:
    path.write_text(json.dumps({"allowed_tools": list(tool_names)}), encoding="utf-8")


@pytest.mark.anyio
async def test_list_tools_exposes_exactly_the_allowlisted_subset(tmp_path: Path) -> None:
    selection = tmp_path / "capsule-selection.json"
    write_allowlist(selection, "tool-2", "tool-7")

    async with connected_session(fake_upstream()) as upstream:
        gateway = McpGateway(upstream, AllowlistFile(selection))
        async with connected_session(gateway.server) as client:
            result = await client.list_tools()

    assert [tool.name for tool in result.tools] == ["tool-2", "tool-7"]


@pytest.mark.anyio
async def test_blocked_call_returns_policy_error_and_writes_audit_event(tmp_path: Path) -> None:
    selection = tmp_path / "capsule-selection.json"
    write_allowlist(selection, "tool-2", "tool-7")
    audit_events: list[GatewayAuditEvent] = []

    async with connected_session(fake_upstream()) as upstream:
        gateway = McpGateway(upstream, AllowlistFile(selection), audit_events.append)
        async with connected_session(gateway.server) as client:
            result = await client.call_tool("tool-9", {})

    assert result.isError is True
    assert result.content[0].type == "text"
    assert "blocked by gateway policy" in result.content[0].text
    assert audit_events == [
        GatewayAuditEvent(tool_name="tool-9", reason="tool is not allowlisted")
    ]


@pytest.mark.anyio
async def test_allowlist_hot_reloads_after_selection_file_changes(tmp_path: Path) -> None:
    selection = tmp_path / "capsule-selection.json"
    write_allowlist(selection, "tool-1")

    async with connected_session(fake_upstream()) as upstream:
        gateway = McpGateway(upstream, AllowlistFile(selection))
        async with connected_session(gateway.server) as client:
            before = await client.list_tools()
            write_allowlist(selection, "tool-8")
            after = await client.list_tools()

    assert [tool.name for tool in before.tools] == ["tool-1"]
    assert [tool.name for tool in after.tools] == ["tool-8"]


@pytest.mark.anyio
async def test_upstream_disconnect_returns_a_clear_error_without_hanging(tmp_path: Path) -> None:
    selection = tmp_path / "capsule-selection.json"
    write_allowlist(selection, "tool-2")

    async with connected_session(fake_upstream()) as upstream:
        gateway = McpGateway(upstream, AllowlistFile(selection), upstream_timeout=0.1)

    async with connected_session(gateway.server) as client:
        with anyio.fail_after(1):
            result = await client.call_tool("tool-2", {})

    assert result.isError is True
    assert result.content[0].type == "text"
    assert "upstream unavailable" in result.content[0].text
