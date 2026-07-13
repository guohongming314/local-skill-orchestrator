"""Read-only Codex MCP configuration adapter."""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vibe.inventory.adapters.base import (
    AdapterDiscovery,
    AdapterProvenance,
    AdapterScanError,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)


class CodexMcpAdapter:
    adapter_id = "codex-mcp"

    def __init__(
        self,
        *,
        config: Path,
        executable_resolver: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._config = config.resolve()
        self._resolve = executable_resolver

    def discover(self) -> tuple[AdapterDiscovery, ...]:
        servers = self._servers()
        return tuple(AdapterDiscovery(locator=name) for name in sorted(servers))

    def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
        servers = self._servers()
        value = servers.get(discovery.locator)
        if not isinstance(value, dict):
            raise AdapterScanError(f"invalid MCP server metadata: {discovery.locator}")
        command = value.get("command")
        url = value.get("url")
        details = ["configured"]
        permissions: set[Permission] = set()
        verified = True
        if isinstance(command, str) and command:
            permissions.add(Permission.EXECUTE_COMMAND)
            if self._resolve(command) is None:
                details.append(f"missing_command:{command}")
                verified = False
        elif isinstance(url, str) and url:
            permissions.add(Permission.NETWORK)
        else:
            details.append("missing_transport")
            verified = False
        connected = value.get("connected")
        if connected is True:
            details.append("connected")
        elif connected is False:
            details.append("disconnected")
        else:
            details.append("connection_unknown")
        capabilities = value.get("capabilities")
        provides = (
            tuple(sorted(str(item) for item in capabilities))
            if isinstance(capabilities, list) and capabilities
            else ("mcp-tools",)
        )
        safe = {
            "capabilities": provides,
            "command": command if isinstance(command, str) else None,
            "connected": connected if isinstance(connected, bool) else None,
            "env_names": sorted(value.get("env", {}).keys())
            if isinstance(value.get("env"), dict)
            else [],
            "has_url": isinstance(url, str) and bool(url),
            "name": discovery.locator,
        }
        digest = hashlib.sha256(
            json.dumps(safe, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        source = f"{self._config}#mcp_servers.{discovery.locator}"
        manifest = CapabilityManifest(
            capability_id=f"mcp.{discovery.locator}",
            name=discovery.locator,
            kind=CapabilityKind.MCP,
            scope=CapabilityScope.USER,
            source=source,
            provides=provides,
            permissions=frozenset(permissions),
            content_digest=digest,
            verified=verified,
        )
        return AdapterScanResult(
            manifest=manifest,
            provenance=AdapterProvenance(adapter_id=self.adapter_id, locator=source),
            verification=AdapterVerification(verified=verified, details=tuple(sorted(details))),
        )

    def _servers(self) -> dict[str, Any]:
        if not self._config.is_file():
            return {}
        try:
            data = tomllib.loads(self._config.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
            raise AdapterScanError(f"cannot parse Codex config metadata: {error}") from error
        servers = data.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise AdapterScanError("mcp_servers must be a table")
        return servers
