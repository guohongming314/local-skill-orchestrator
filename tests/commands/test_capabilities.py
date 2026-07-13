from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

from typer.testing import CliRunner

from vibe.cli import app

runner = CliRunner()


def write_fixture(root: Path) -> tuple[Path, Path, str]:
    config = root / "config.toml"
    secret = "SUPER-SECRET-MCP-TOKEN"
    config.write_text(
        "\n".join(
            (
                "[mcp_servers.local-search]",
                'command = "missing-mcp-command"',
                'args = ["serve"]',
                'env = { API_TOKEN = "' + secret + '" }',
                'capabilities = ["semantic-search", "memory"]',
                "connected = false",
            )
        ),
        encoding="utf-8",
    )
    plugins = root / "plugins"
    plugin = plugins / "example-plugin"
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / "hooks").mkdir()
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "example-plugin",
                "version": "1.2.3",
                "description": "Example local plugin",
                "hooks": "hooks/hooks.json",
                "interface": {
                    "capabilities": ["project-analysis"],
                    "compatibility": "codex>=1",
                },
            }
        ),
        encoding="utf-8",
    )
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "permissions": ["read-project", "network"],
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python safe_hook.py",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return config, plugins, secret


def invoke(
    action: list[str], *, config: Path, plugins: Path, database: Path
) -> Any:
    return runner.invoke(
        app,
        [
            "capabilities",
            *action,
            "--config",
            str(config),
            "--plugins-root",
            str(plugins),
            "--database",
            str(database),
            "--json",
        ],
    )


def test_list_reports_source_scope_permissions_compatibility_and_status(tmp_path: Path) -> None:
    config, plugins, secret = write_fixture(tmp_path)

    result = invoke(
        ["list"], config=config, plugins=plugins, database=tmp_path / "state.sqlite3"
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    by_id = {item["capability_id"]: item for item in payload["capabilities"]}
    assert {"mcp.local-search", "plugin.example-plugin"} <= set(by_id)
    assert "hook.example-plugin" in by_id
    mcp = by_id["mcp.local-search"]
    assert mcp["source"].endswith("config.toml#mcp_servers.local-search")
    assert mcp["scope"] == "user"
    assert mcp["permissions"] == ["execute-command"]
    assert mcp["compatibility"] == "configured; disconnected"
    assert mcp["status"] == "unverified"
    plugin = by_id["plugin.example-plugin"]
    assert plugin["compatibility"] == "codex>=1"
    assert secret not in result.stdout


def test_explain_resolves_capability_with_provenance(tmp_path: Path) -> None:
    config, plugins, secret = write_fixture(tmp_path)

    result = invoke(
        ["explain", "plugin.example-plugin"],
        config=config,
        plugins=plugins,
        database=tmp_path / "state.sqlite3",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["capability_id"] == "plugin.example-plugin"
    assert payload["provenance"]["adapter_id"] == "codex-plugin"
    assert payload["provenance"]["locator"].endswith("plugin.json")
    assert payload["verification"]["verified"] is True
    assert secret not in result.stdout


def test_doctor_reports_missing_dependencies_and_overbroad_hooks_without_secrets(
    tmp_path: Path,
) -> None:
    config, plugins, secret = write_fixture(tmp_path)
    database = tmp_path / "state.sqlite3"

    result = invoke(
        ["doctor"], config=config, plugins=plugins, database=database
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    findings = payload["findings"]
    assert any("missing_command:missing-mcp-command" in item["details"] for item in findings)
    assert any("over_broad_permission:network" in item["details"] for item in findings)
    assert secret not in result.stdout
    assert secret.encode() not in database.read_bytes()


def test_doctor_reports_malformed_plugin_and_hook_metadata(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    plugins = tmp_path / "plugins"
    bad_plugin = plugins / "bad-plugin" / ".codex-plugin"
    bad_plugin.mkdir(parents=True)
    (bad_plugin / "plugin.json").write_text("{not-json", encoding="utf-8")
    bad_hooks = plugins / "hook-plugin"
    (bad_hooks / ".codex-plugin").mkdir(parents=True)
    (bad_hooks / "hooks").mkdir()
    (bad_hooks / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "hook-plugin", "description": "x", "hooks": "hooks/hooks.json"}),
        encoding="utf-8",
    )
    (bad_hooks / "hooks" / "hooks.json").write_text("[]", encoding="utf-8")

    result = invoke(
        ["doctor"],
        config=config,
        plugins=plugins,
        database=tmp_path / "state.sqlite3",
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    codes = {item["code"] for item in payload["diagnostics"]}
    assert "adapter_scan_failed" in codes
    assert any("plugin.json" in item["message"] for item in payload["diagnostics"])
    assert any("hooks metadata" in item["message"] for item in payload["diagnostics"])


def test_list_persists_safe_inventory_and_verification_records(tmp_path: Path) -> None:
    config, plugins, secret = write_fixture(tmp_path)
    database = tmp_path / "state.sqlite3"

    first = invoke(["list"], config=config, plugins=plugins, database=database)
    second = invoke(["list"], config=config, plugins=plugins, database=database)

    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout
    with sqlite3.connect(database) as connection:
        inventory_row = connection.execute(
            "SELECT inventory_json FROM inventory_cache"
        ).fetchone()
        assert inventory_row is not None
        inventory_json = cast(str, inventory_row[0])
        verification_json = "".join(
            cast(str, row[0])
            for row in connection.execute(
                "SELECT details_json FROM capability_verifications"
            ).fetchall()
        )
    persisted = inventory_json + verification_json
    assert "plugin.example-plugin" in persisted
    assert "mcp.local-search" in persisted
    assert secret not in persisted


def test_explain_unknown_id_is_actionable(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    plugins = tmp_path / "plugins"
    plugins.mkdir()

    result = invoke(
        ["explain", "plugin.missing"],
        config=config,
        plugins=plugins,
        database=tmp_path / "state.sqlite3",
    )

    assert result.exit_code == 2
    assert "unknown capability ID: plugin.missing" in result.stderr




