from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from tests.scenarios.builders import build_scenario
from vibe.cli import app

pytestmark = pytest.mark.validation

runner = CliRunner()


def _answers(
    tmp_path: Path, name: str, *, lifecycle_stage: str = "active-development"
) -> Path:
    path = tmp_path / f"{name}-answers.json"
    path.write_text(
        json.dumps(
            {
                "goal": "Build a blank web application",
                "lifecycle_stage": lifecycle_stage,
                "risk_level": "medium",
                "project_type": "web-application",
                "preferences": {"project_type": "web-application"},
            }
        ),
        encoding="utf-8",
    )
    return path


def _init(
    root: Path,
    tmp_path: Path,
    *,
    run_id: str,
    remote_discovery: bool,
    dry_run: bool = True,
    lifecycle_stage: str = "active-development",
) -> Any:
    arguments = [
        "init",
        "--path",
        str(root),
        "--run-id",
        run_id,
        "--checkpoints",
        str(tmp_path / f"{run_id}.sqlite3"),
        "--answers",
        str(_answers(tmp_path, run_id, lifecycle_stage=lifecycle_stage)),
        "--confirm",
        "--recommendation-decision",
        "*=defer",
        "--json",
    ]
    if dry_run:
        arguments.append("--dry-run")
    if remote_discovery:
        arguments.extend(("--remote-discovery", "--remote-offline"))
    return runner.invoke(app, arguments)


def _capability_resolution(
    payload: dict[str, Any], capability: str
) -> dict[str, Any]:
    return next(
        item
        for item in payload["resolution"]["resolutions"]
        if item["requirement"] == capability and item["status"] in {"gap", "selected"}
    )


def _browser_resolution(payload: dict[str, Any]) -> dict[str, Any]:
    return _capability_resolution(payload, "browser.validation")


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


def test_gap_to_approved_remote_install_doctor_and_uninstall_round_trip(
    tmp_path: Path,
) -> None:
    built = build_scenario("blank-web-remote", tmp_path / "web")

    discovered = _init(
        built.root,
        tmp_path,
        run_id="remote-discovery",
        remote_discovery=True,
        dry_run=False,
    )

    assert discovered.exit_code == 0, discovered.output
    browser = _browser_resolution(json.loads(discovered.stdout))
    assert browser["status"] == "gap"
    remote = next(
        item
        for item in browser["recommendation"]["candidates"]
        if item["provider"] == "browser-testing"
    )
    assert remote["approval_required"] == "approve once"
    assert "fit=" in remote["why"]
    assert "trust=" in remote["why"]
    assert "risk=" in remote["why"]
    assert remote["maintenance_score"] >= 0
    assert remote["popularity_score"] >= 0
    assert remote["total_score"] >= 0

    baseline = _tree(built.root)
    installed = runner.invoke(
        app,
        [
            "install",
            "browser-testing",
            "--path",
            str(built.root),
            "--candidate-file",
            str(built.root / ".scenario/registry/browser-testing.json"),
            "--approve",
        ],
    )
    assert installed.exit_code == 0, installed.output

    lock = yaml.safe_load(
        (built.root / ".ai-project/capabilities.lock").read_text(encoding="utf-8")
    )
    provider = next(
        item for item in lock["providers"] if item["provider_id"] == "skill.browser-testing"
    )
    assert provider["version"] == "1.2.3"
    assert provider["content_digest"].startswith("sha256:")

    rebound = _init(
        built.root,
        tmp_path,
        run_id="remote-installed",
        remote_discovery=True,
        dry_run=False,
    )
    assert rebound.exit_code == 0, rebound.output
    selected = _browser_resolution(json.loads(rebound.stdout))
    assert selected["status"] == "selected"
    assert selected["capability_id"] == "skill.browser-testing"

    doctor = runner.invoke(app, ["doctor", "--path", str(built.root), "--json"])
    assert doctor.exit_code == 0, doctor.output
    assert json.loads(doctor.stdout)["status"] == "healthy"

    uninstalled = runner.invoke(
        app,
        ["uninstall", "browser-testing", "--path", str(built.root)],
    )
    assert uninstalled.exit_code == 0, uninstalled.output

    reconciled = _init(
        built.root,
        tmp_path,
        run_id="remote-uninstalled",
        remote_discovery=True,
        dry_run=False,
    )
    assert reconciled.exit_code == 0, reconciled.output
    assert _tree(built.root) == baseline


def test_unapproved_remote_install_is_refused_without_changes(tmp_path: Path) -> None:
    built = build_scenario("blank-web-remote", tmp_path / "unapproved")
    before = _tree(built.root)

    result = runner.invoke(
        app,
        [
            "install",
            "browser-testing",
            "--path",
            str(built.root),
            "--candidate-file",
            str(built.root / ".scenario/registry/browser-testing.json"),
        ],
    )

    assert result.exit_code != 0
    assert "approval" in result.stdout.lower()
    assert _tree(built.root) == before


def test_digest_tampered_remote_candidate_is_blocked(tmp_path: Path) -> None:
    built = build_scenario("blank-web-remote", tmp_path / "tampered")
    bundle_path = built.root / ".scenario/registry/browser-testing.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["package"]["files"][0]["content"] += "\nTampered after publication.\n"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    before = _tree(built.root)

    result = runner.invoke(
        app,
        [
            "install",
            "browser-testing",
            "--path",
            str(built.root),
            "--candidate-file",
            str(bundle_path),
            "--approve",
        ],
    )

    assert result.exit_code != 0
    failure = f"{result.stdout} {result.exception}".lower()
    assert "digest" in failure
    assert _tree(built.root) == before


def test_offline_discovery_degrades_to_local_only_recommendations(tmp_path: Path) -> None:
    built = build_scenario("blank-web-remote", tmp_path / "offline")
    (built.root / ".ai-project/remote-candidates.json").unlink()

    result = _init(
        built.root,
        tmp_path,
        run_id="remote-offline",
        remote_discovery=True,
    )

    assert result.exit_code == 0, result.output
    browser = _browser_resolution(json.loads(result.stdout))
    assert [item["provider"] for item in browser["recommendation"]["candidates"]] == [
        "playwright",
        "chrome-devtools",
    ]


def test_disabling_discovery_reproduces_e11_recommendations(tmp_path: Path) -> None:
    built = build_scenario("blank-web-remote", tmp_path / "disabled")

    result = _init(
        built.root,
        tmp_path,
        run_id="remote-disabled",
        remote_discovery=False,
    )

    assert result.exit_code == 0, result.output
    browser = _browser_resolution(json.loads(result.stdout))
    assert [item["provider"] for item in browser["recommendation"]["candidates"]] == [
        "playwright",
        "chrome-devtools",
    ]


def test_non_browser_remote_candidate_reaches_gap_recommendation(tmp_path: Path) -> None:
    built = build_scenario("blank-web-remote", tmp_path / "non-browser")
    candidates_path = built.root / ".ai-project/remote-candidates.json"
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    remote = dict(payload["candidates"][0])
    remote.update(
        {
            "candidate_ref": "registry:cli-tool/release-safety@1.0.0",
            "name": "release-safety",
            "provides": ["release.rollback"],
            "version": "1.0.0",
        }
    )
    remote["provenance"] = dict(remote["provenance"])
    remote["provenance"]["source"] = remote["candidate_ref"]
    payload["candidates"].append(remote)
    payload["evidence"][remote["candidate_ref"]] = {
        "adoption": 250,
        "maintenance": 90,
        "platforms": ["codex"],
        "project_fact_matches": ["lifecycle_stage:production"],
        "scan_flags": [],
    }
    candidates_path.write_text(json.dumps(payload), encoding="utf-8")

    result = _init(
        built.root,
        tmp_path,
        run_id="remote-non-browser",
        remote_discovery=True,
        lifecycle_stage="production",
    )

    assert result.exit_code == 0, result.output
    resolution = _capability_resolution(
        json.loads(result.stdout), "release.rollback"
    )
    assert resolution["status"] == "gap"
    assert [
        item["provider"] for item in resolution["recommendation"]["candidates"]
    ] == ["deployment-rollback", "release-safety"]
    remote_recommendation = resolution["recommendation"]["candidates"][1]
    assert remote_recommendation["permission_level"] == "L1"
    assert "fit=" in remote_recommendation["why"]
    assert "trust=" in remote_recommendation["why"]
    assert "risk=" in remote_recommendation["why"]
