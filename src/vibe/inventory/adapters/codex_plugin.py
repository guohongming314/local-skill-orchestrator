"""Read-only Codex plugin manifest adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from vibe.inventory.adapters.base import (
    AdapterDiscovery,
    AdapterProvenance,
    AdapterScanError,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.models.capability import CapabilityKind, CapabilityManifest, CapabilityScope


class CodexPluginAdapter:
    adapter_id = "codex-plugin"

    def __init__(self, *, roots: tuple[Path, ...]) -> None:
        self._roots = tuple(root.resolve() for root in roots)

    def discover(self) -> tuple[AdapterDiscovery, ...]:
        paths = {
            path.resolve()
            for root in self._roots
            if root.is_dir()
            for path in root.rglob(".codex-plugin/plugin.json")
            if path.is_file()
        }
        return tuple(AdapterDiscovery(locator=str(path)) for path in sorted(paths))

    def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
        path = Path(discovery.locator).resolve()
        data, raw = _json_object(path, "plugin.json")
        name = _required_string(data, "name", "plugin.json")
        description = _required_string(data, "description", "plugin.json")
        details: list[str] = []
        interface = data.get("interface")
        capabilities: tuple[str, ...] = ()
        if isinstance(interface, dict):
            raw_capabilities = interface.get("capabilities")
            if isinstance(raw_capabilities, list):
                capabilities = tuple(sorted(str(item) for item in raw_capabilities))
            compatibility = interface.get("compatibility")
            if isinstance(compatibility, str) and compatibility:
                details.append(f"compatibility:{compatibility}")
        hooks = data.get("hooks")
        verified = True
        if isinstance(hooks, str) and hooks:
            hook_path = (path.parent.parent / hooks).resolve()
            if not hook_path.is_relative_to(path.parent.parent) or not hook_path.is_file():
                details.append(f"missing_dependency:{hooks}")
                verified = False
            else:
                details.append(f"dependency:{hooks}")
        provides = capabilities or (description,)
        digest = hashlib.sha256(raw).hexdigest()
        manifest = CapabilityManifest(
            capability_id=f"plugin.{name}",
            name=name,
            kind=CapabilityKind.PLUGIN,
            scope=CapabilityScope.USER,
            source=str(path),
            provides=provides,
            version=str(data["version"]) if data.get("version") is not None else None,
            content_digest=digest,
            verified=verified,
        )
        return AdapterScanResult(
            manifest=manifest,
            provenance=AdapterProvenance(adapter_id=self.adapter_id, locator=str(path)),
            verification=AdapterVerification(verified=verified, details=tuple(sorted(details))),
        )


def _json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AdapterScanError(f"cannot parse {label} metadata at {path}: {error}") from error
    if not isinstance(data, dict):
        raise AdapterScanError(f"{label} metadata must be an object: {path}")
    return data, raw


def _required_string(data: dict[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise AdapterScanError(f"{label} field {key!r} is required")
    return value
