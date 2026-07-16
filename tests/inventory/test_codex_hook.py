from __future__ import annotations

import json
from pathlib import Path

from vibe.inventory.adapters.codex_hook import CodexHookAdapter
from vibe.models.capability import CapabilityScope, Permission


def _write_hooks(path: Path, *, permission: str = "execute-command") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "permissions": [permission],
                            "hooks": [{"type": "command", "command": "python3 hook.py"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )


def test_discovers_explicit_project_hooks_with_project_scope(tmp_path: Path) -> None:
    project = tmp_path / "project"
    hook_path = project / ".codex" / "hooks.json"
    _write_hooks(hook_path)

    adapter = CodexHookAdapter(roots=(tmp_path / "plugins",), project_root=project)
    discoveries = adapter.discover()
    result = adapter.scan(next(item for item in discoveries if item.locator == str(hook_path)))

    assert result.manifest.capability_id == "hook.project"
    assert result.manifest.scope is CapabilityScope.PROJECT
    assert result.manifest.permissions == frozenset({Permission.EXECUTE_COMMAND})
    assert result.manifest.provides == ("trigger:PreToolUse",)


def test_plugin_hook_discovery_remains_user_scoped(tmp_path: Path) -> None:
    plugin = tmp_path / "plugins" / "example"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "example", "hooks": "hooks/hooks.json"}),
        encoding="utf-8",
    )
    _write_hooks(plugin / "hooks" / "hooks.json")

    adapter = CodexHookAdapter(roots=(tmp_path / "plugins",), project_root=tmp_path)
    result = adapter.scan(
        next(item for item in adapter.discover() if "plugins/example/hooks" in item.locator)
    )

    assert result.manifest.capability_id == "hook.example"
    assert result.manifest.scope is CapabilityScope.USER


def test_project_hook_with_explicit_network_permission_is_unverified(tmp_path: Path) -> None:
    hook_path = tmp_path / ".codex" / "hooks.json"
    _write_hooks(hook_path, permission="network")

    adapter = CodexHookAdapter(roots=(), project_root=tmp_path)
    result = adapter.scan(adapter.discover()[0])

    assert result.verification.verified is False
    assert "over_broad_permission:network" in result.verification.details
