"""Read-only Codex Hook metadata adapter; Hooks are never executed."""

from __future__ import annotations

import hashlib
from pathlib import Path

from vibe.inventory.adapters.base import (
    AdapterDiscovery,
    AdapterProvenance,
    AdapterScanError,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.inventory.adapters.codex_plugin import _json_object, _required_string
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)

_PERMISSION_MAP = {permission.value: permission for permission in Permission}
_OVER_BROAD = frozenset({Permission.NETWORK, Permission.WRITE_PROJECT})


class CodexHookAdapter:
    adapter_id = "codex-hook"

    def __init__(self, *, roots: tuple[Path, ...], project_root: Path | None = None) -> None:
        self._roots = tuple(root.resolve() for root in roots)
        self._project_root = project_root.resolve() if project_root is not None else None

    def discover(self) -> tuple[AdapterDiscovery, ...]:
        discoveries: list[AdapterDiscovery] = []
        if self._project_root is not None:
            project_hooks = self._project_root / ".codex" / "hooks.json"
            if project_hooks.is_file():
                discoveries.append(AdapterDiscovery(locator=str(project_hooks)))
        for root in self._roots:
            if not root.is_dir():
                continue
            for manifest in root.rglob(".codex-plugin/plugin.json"):
                try:
                    plugin, _raw = _json_object(manifest, "plugin.json")
                except AdapterScanError:
                    continue
                hooks = plugin.get("hooks")
                if isinstance(hooks, str) and hooks:
                    hook_path = (manifest.parent.parent / hooks).resolve()
                    discoveries.append(AdapterDiscovery(locator=str(hook_path)))
        return tuple(sorted(set(discoveries), key=lambda item: item.locator))

    def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
        path = Path(discovery.locator).resolve()
        data, raw = _json_object(path, "hooks metadata")
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            raise AdapterScanError(f"hooks metadata field 'hooks' must be an object: {path}")
        is_project = (
            self._project_root is not None and path == self._project_root / ".codex" / "hooks.json"
        )
        if is_project:
            hook_name = "project"
            scope = CapabilityScope.PROJECT
            details: list[str] = ["project_local", "trust_required"]
        else:
            plugin_manifest = path.parent.parent / ".codex-plugin" / "plugin.json"
            plugin_data, _plugin_raw = _json_object(plugin_manifest, "plugin.json")
            hook_name = _required_string(plugin_data, "name", "plugin.json")
            scope = CapabilityScope.USER
            details = [f"plugin:{hook_name}"]
        permissions: set[Permission] = set()
        triggers: list[str] = []
        malformed = False
        for trigger, entries in sorted(hooks.items()):
            if not isinstance(entries, list):
                details.append(f"malformed_trigger:{trigger}")
                malformed = True
                continue
            triggers.append(str(trigger))
            for entry in entries:
                if not isinstance(entry, dict):
                    details.append(f"malformed_entry:{trigger}")
                    malformed = True
                    continue
                matcher = entry.get("matcher")
                if isinstance(matcher, str) and matcher:
                    details.append(f"trigger:{trigger}:matcher:{matcher}")
                else:
                    details.append(f"trigger:{trigger}")
                declared = entry.get("permissions", [])
                if isinstance(declared, list):
                    for value in declared:
                        permission = _PERMISSION_MAP.get(str(value))
                        if permission is not None:
                            permissions.add(permission)
                commands = entry.get("hooks", [])
                if isinstance(commands, list) and any(
                    isinstance(command, dict) and command.get("type") == "command"
                    for command in commands
                ):
                    permissions.add(Permission.EXECUTE_COMMAND)
        for permission in sorted(permissions & _OVER_BROAD, key=lambda item: item.value):
            details.append(f"over_broad_permission:{permission.value}")
        verified = not malformed and not bool(permissions & _OVER_BROAD)
        digest = hashlib.sha256(raw).hexdigest()
        manifest = CapabilityManifest(
            capability_id=f"hook.{hook_name}",
            name=f"{hook_name} hooks",
            kind=CapabilityKind.HOOK,
            scope=scope,
            source=str(path),
            provides=tuple(f"trigger:{trigger}" for trigger in sorted(triggers)) or ("hooks",),
            permissions=frozenset(permissions),
            content_digest=digest,
            verified=verified,
        )
        return AdapterScanResult(
            manifest=manifest,
            provenance=AdapterProvenance(
                adapter_id=self.adapter_id,
                locator=(str(path) if is_project else f"{path}#plugin={hook_name}"),
            ),
            verification=AdapterVerification(verified=verified, details=tuple(sorted(details))),
        )
