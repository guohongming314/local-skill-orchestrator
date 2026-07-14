from __future__ import annotations

from pathlib import Path

import pytest

from vibe.commands.project_plan import build_project_plan
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot
from vibe.models.resolution import ResolutionStatus
from vibe.models.risk import RiskLevel
from vibe.practices.models import RequirementStrength


def _blueprint(root: Path) -> Blueprint:
    return Blueprint(
        project_name=root.name,
        goal="Build a project",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        repository_digest="repository-digest",
    )


def _repository(root: Path, project_type: str) -> RepositorySnapshot:
    return RepositorySnapshot(
        root=root,
        is_empty=True,
        facts=(
            RepositoryFact(
                key="project_type",
                value=project_type,
                confidence=FactConfidence.CONFIRMED,
                sources=("interview:project.type",),
            ),
        ),
        source_digest="repository-digest",
    )


def test_blank_web_application_uses_web_and_base_practice_packs(tmp_path: Path) -> None:
    plan = build_project_plan(
        tmp_path,
        _blueprint(tmp_path),
        _repository(tmp_path, "web-application"),
    )

    requirements = {item.capability: item for item in plan.requirements}
    browser = requirements["browser.validation"]
    assert browser.strength is RequirementStrength.RECOMMENDED
    assert browser.originating_packs == ("web-application",)
    assert browser.reasons == ("Validate user-visible browser behavior",)
    assert {"repository.exploration", "quality.gates"} <= requirements.keys()

    browser_decisions = [
        item for item in plan.resolution.resolutions if item.requirement == "browser.validation"
    ]
    assert len(browser_decisions) == 1
    assert browser_decisions[0].status is ResolutionStatus.GAP


def test_non_web_project_has_no_browser_requirement(tmp_path: Path) -> None:
    plan = build_project_plan(
        tmp_path,
        _blueprint(tmp_path),
        _repository(tmp_path, "cli-tool"),
    )

    assert "browser.validation" not in {
        item.capability for item in plan.requirements
    }


def test_repeat_plan_is_deterministic(tmp_path: Path) -> None:
    blueprint = _blueprint(tmp_path)
    repository = _repository(tmp_path, "web-application")

    first = build_project_plan(tmp_path, blueprint, repository)
    second = build_project_plan(tmp_path, blueprint, repository)

    assert first.inventory.inventory_digest == second.inventory.inventory_digest
    assert first.resolution == second.resolution
    assert first.requirements == second.requirements


def test_init_inventory_lists_user_codex_mcp_with_permissions_and_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    executable = tmp_path / "chrome-devtools-mcp"
    executable.write_text(
        "#!/bin/sh\necho chrome-devtools-mcp 1.0.0\n", encoding="utf-8"
    )
    executable.chmod(0o755)
    (codex_home / "config.toml").write_text(
        "\n".join(
            (
                "[mcp_servers.chrome-devtools]",
                f'command = "{executable}"',
                "connected = true",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    plan = build_project_plan(
        tmp_path,
        _blueprint(tmp_path),
        _repository(tmp_path, "web-application"),
    )

    chrome = next(
        item
        for item in plan.inventory.capabilities
        if item.manifest.capability_id == "mcp.chrome-devtools"
    )
    assert chrome.manifest.scope.value == "user"
    assert {permission.value for permission in chrome.manifest.permissions} == {
        "execute-command"
    }
    assert chrome.manifest.verified is True
    assert chrome.verification.verified is True
    assert chrome.verification.details == ("configured", "connected")
