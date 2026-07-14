from __future__ import annotations

from pathlib import Path

from vibe.inventory.adapters.codex_mcp import CodexMcpAdapter


def test_chrome_devtools_uses_known_provider_capabilities(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '\n'.join(
            (
                '[mcp_servers.chrome-devtools]',
                'command = "chrome-devtools-mcp"',
            )
        ),
        encoding="utf-8",
    )
    adapter = CodexMcpAdapter(
        config=config,
        executable_resolver=lambda command: f"/tools/{command}",
    )

    result = adapter.scan(adapter.discover()[0])

    assert "browser.validation" in result.manifest.provides


def test_unknown_provider_keeps_mcp_tools_fallback(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.custom]\nurl = "https://example.test/mcp"\n', encoding="utf-8")
    adapter = CodexMcpAdapter(config=config)

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.provides == ("mcp-tools",)


def test_explicit_capabilities_override_known_provider_taxonomy(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '\n'.join(
            (
                '[mcp_servers.chrome-devtools]',
                'url = "https://example.test/mcp"',
                'capabilities = ["custom.browser"]',
            )
        ),
        encoding="utf-8",
    )
    adapter = CodexMcpAdapter(config=config)

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.provides == ("custom.browser",)
