"""Bridge phase-scoped capsule capabilities to hard-routing exposure."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from vibe.models.capability import CapabilityManifest


@dataclass(frozen=True)
class CapabilityToolBinding:
    """Concrete MCP tools supplied by one capability manifest/provider."""

    capability_id: str
    provides: tuple[str, ...]
    server_id: str
    tool_names: tuple[str, ...]

    @classmethod
    def from_manifest(
        cls,
        manifest: CapabilityManifest,
        *,
        server_id: str,
        tool_names: tuple[str, ...],
    ) -> CapabilityToolBinding:
        """Bind discovered tools using the manifest's taxonomy-resolved provides IDs."""
        return cls(
            capability_id=manifest.capability_id,
            provides=manifest.provides,
            server_id=server_id,
            tool_names=tool_names,
        )


@dataclass(frozen=True)
class PhaseExposureRequest:
    """Validated phase selection passed to a host adapter."""

    phase: str
    selected_capabilities: tuple[str, ...]
    selected_server_ids: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    known_server_ids: tuple[str, ...]
    exposure_digest: str


@dataclass(frozen=True)
class HostExposure:
    """Host-specific session configuration for a phase boundary."""

    thread_config: dict[str, object]
    transition: str = "start"


class HostAdapter(Protocol):
    """Prepare a hard-routed phase session without changing capability selection."""

    def expose(self, request: PhaseExposureRequest) -> HostExposure: ...


@dataclass(frozen=True)
class PhaseExposure:
    """Effective gateway and host exposure for one compiled capsule."""

    phase: str
    selected_capabilities: tuple[str, ...]
    selected_server_ids: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    exposure_digest: str
    thread_config: dict[str, object]
    transition: str


class GatewayPhaseExposure:
    """Resolve manifest/taxonomy bindings and atomically rewrite the gateway allowlist."""

    def __init__(
        self,
        *,
        allowlist_path: Path,
        bindings: tuple[CapabilityToolBinding, ...],
        host_adapter: HostAdapter | None = None,
    ) -> None:
        self.allowlist_path = allowlist_path
        self.bindings = bindings
        self.host_adapter = host_adapter

    def expose(self, phase: str, selected_capabilities: tuple[str, ...]) -> PhaseExposure:
        selected = set(selected_capabilities)
        matched = tuple(
            binding
            for binding in self.bindings
            if binding.capability_id in selected or selected.intersection(binding.provides)
        )
        server_ids = tuple(sorted({binding.server_id for binding in matched}))
        tools = tuple(sorted({tool for binding in matched for tool in binding.tool_names}))
        known_servers = tuple(sorted({binding.server_id for binding in self.bindings}))
        digest = _exposure_digest(phase, selected_capabilities, server_ids, tools)
        request = PhaseExposureRequest(
            phase=phase,
            selected_capabilities=tuple(sorted(selected_capabilities)),
            selected_server_ids=server_ids,
            allowed_tools=tools,
            known_server_ids=known_servers,
            exposure_digest=digest,
        )
        host = (
            self.host_adapter.expose(request)
            if self.host_adapter is not None
            else HostExposure(thread_config={}, transition="start")
        )
        self._write_allowlist(tools)
        return PhaseExposure(
            phase=phase,
            selected_capabilities=request.selected_capabilities,
            selected_server_ids=server_ids,
            allowed_tools=tools,
            exposure_digest=digest,
            thread_config=host.thread_config,
            transition=host.transition,
        )

    def _write_allowlist(self, tools: tuple[str, ...]) -> None:
        self.allowlist_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.allowlist_path.with_suffix(self.allowlist_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"allowed_tools": list(tools)}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.allowlist_path)


def _exposure_digest(
    phase: str,
    selected_capabilities: tuple[str, ...],
    server_ids: tuple[str, ...],
    tools: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "phase": phase,
            "selected_capabilities": sorted(selected_capabilities),
            "selected_server_ids": server_ids,
            "allowed_tools": tools,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(payload).hexdigest()
