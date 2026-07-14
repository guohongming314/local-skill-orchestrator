from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

from tests.scenarios.builders import build_scenario
from vibe.cli import app

runner = CliRunner()


def _answers(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}-answers.json"
    path.write_text(
        json.dumps(
            {
                "goal": "Build a blank web application",
                "lifecycle_stage": "active-development",
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
        str(_answers(tmp_path, run_id)),
        "--confirm",
        "--json",
    ]
    if dry_run:
        arguments.append("--dry-run")
    if remote_discovery:
        arguments.append("--remote-discovery")
    return runner.invoke(app, arguments)


def _browser_resolution(payload: dict[str, Any]) -> dict[str, Any]:
    return next(
        item
        for item in payload["resolution"]["resolutions"]
        if item["requirement"] == "browser.validation" and item["status"] in {"gap", "selected"}
    )


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
