"""MCP gateway that exposes only capsule-selected upstream tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import anyio
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from vibe.routing.allowlist import AllowlistError, AllowlistFile

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GatewayAuditEvent:
    """A denied gateway tool-call attempt."""

    tool_name: str
    reason: str


AuditSink = Callable[[GatewayAuditEvent], None]


class McpGateway:
    """Proxy one upstream MCP session through an exact, hot-reloaded allowlist."""

    def __init__(
        self,
        upstream: ClientSession,
        allowlist: AllowlistFile,
        audit_sink: AuditSink | None = None,
        *,
        upstream_timeout: float = 5.0,
    ) -> None:
        self._upstream = upstream
        self._allowlist = allowlist
        self._audit_sink = audit_sink or self._log_audit_event
        self._upstream_timeout = upstream_timeout
        self.server: Server[object] = Server("vibe-mcp-gateway")
        self._register_handlers()

    def _register_handlers(self) -> None:
        @self.server.list_tools()  # type: ignore[untyped-decorator,no-untyped-call]
        async def list_tools() -> list[Tool]:
            allowed = set(self._allowlist.tools())
            try:
                with anyio.fail_after(self._upstream_timeout):
                    result = await self._upstream.list_tools()
            except TimeoutError as error:
                raise RuntimeError("upstream unavailable: request timed out") from error
            except Exception as error:
                raise RuntimeError(
                    f"upstream unavailable: {type(error).__name__}"
                ) from error
            return [tool for tool in result.tools if tool.name in allowed]

        @self.server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
        async def call_tool(name: str, arguments: dict[str, object]) -> CallToolResult:
            try:
                allowed = self._allowlist.tools()
            except AllowlistError as error:
                return self._error(f"gateway policy unavailable: {error}")

            if name not in allowed:
                event = GatewayAuditEvent(
                    tool_name=name,
                    reason="tool is not allowlisted",
                )
                self._audit_sink(event)
                return self._error(f"blocked by gateway policy: {name}")

            try:
                with anyio.fail_after(self._upstream_timeout):
                    return await self._upstream.call_tool(name, dict(arguments))
            except TimeoutError:
                return self._error("upstream unavailable: request timed out")
            except Exception as error:
                return self._error(f"upstream unavailable: {type(error).__name__}")

    @staticmethod
    def _error(message: str) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text=message)],
            isError=True,
        )

    @staticmethod
    def _log_audit_event(event: GatewayAuditEvent) -> None:
        _LOGGER.warning(
            "blocked MCP tool call: tool=%s reason=%s",
            event.tool_name,
            event.reason,
        )
