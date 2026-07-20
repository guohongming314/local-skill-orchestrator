from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from tests.scenarios.builders import build_scenario
from vibe.cli import app

pytestmark = pytest.mark.validation

runner = CliRunner()

_E18_DOMAINS = {
    "code.relationship-analysis": "codegraph-local",
    "project.continuity-memory": "continuity-memory-local",
    "git.recovery": "git-recovery-local",
    "release.rollback": "release-rollback-local",
}

_EXPECTED_GAP_PROVIDERS = {
    "code.relationship-analysis": ["codegraph"],
    "project.continuity-memory": ["claude-mem"],
    "git.recovery": ["git"],
    "release.rollback": ["deployment-rollback"],
}


def _answers(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}-answers.json"
    path.write_text(
        json.dumps(
            {
                "goal": "Validate production capability coverage",
                "lifecycle_stage": "production",
                "risk_level": "medium",
            }
        ),
        encoding="utf-8",
    )
    return path


def _init(root: Path, tmp_path: Path, run_id: str) -> dict[str, Any]:
    result = runner.invoke(
        app,
        [
            "init",
            "--path",
            str(root),
            "--run-id",
            run_id,
            "--checkpoints",
            str(tmp_path / f"{run_id}.sqlite3"),
            "--answers",
            str(_answers(tmp_path, run_id)),
            "--confirm",
            "--dry-run",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    return cast(dict[str, Any], json.loads(result.stdout))


def _domain_resolutions(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["requirement"]: item
        for item in payload["resolution"]["resolutions"]
        if item["requirement"] in _E18_DOMAINS
        and item["status"] in {"selected", "gap"}
    }


def _install_provider(root: Path, provider: str, capability: str) -> None:
    skill = root / ".agents" / "skills" / provider / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "\n".join(
            [
                "---",
                f"name: {provider}",
                f"description: Local provider for {capability}",
                f"provides: {capability}",
                "permissions: read-project",
                "---",
                "",
                f"Provide {capability} deterministically.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_e18_domains_select_present_local_providers(tmp_path: Path) -> None:
    root = build_scenario("large-monorepo", tmp_path / "selected").root
    for capability, provider in _E18_DOMAINS.items():
        _install_provider(root, provider, capability)

    payload = _init(root, tmp_path, "e18-selected")

    resolutions = _domain_resolutions(payload)
    assert set(resolutions) == set(_E18_DOMAINS)
    assert {
        capability: (item["status"], item["capability_id"])
        for capability, item in resolutions.items()
    } == {
        capability: ("selected", f"skill.{provider}")
        for capability, provider in _E18_DOMAINS.items()
    }


def test_e18_domains_report_ranked_gaps_without_providers(tmp_path: Path) -> None:
    root = build_scenario("large-monorepo", tmp_path / "gaps").root

    payload = _init(root, tmp_path, "e18-gaps")

    resolutions = _domain_resolutions(payload)
    assert set(resolutions) == set(_E18_DOMAINS)
    for capability, expected_providers in _EXPECTED_GAP_PROVIDERS.items():
        resolution = resolutions[capability]
        assert resolution["status"] == "gap"
        assert resolution["capability_id"] is None
        candidates = resolution["recommendation"]["candidates"]
        assert [item["provider"] for item in candidates] == expected_providers
        assert all(item["permissions"] and item["why"] for item in candidates)
