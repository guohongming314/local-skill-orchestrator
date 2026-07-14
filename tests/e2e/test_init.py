from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, cast

import yaml
from typer.testing import CliRunner

from tests.scenarios.builders import build_scenario
from vibe.cli import app
from vibe.materialize.writer import apply_changeset as real_apply_changeset

runner = CliRunner()


def _answers(tmp_path: Path, *, lifecycle: str = "active-development") -> Path:
    path = tmp_path / f"answers-{lifecycle}.json"
    path.write_text(
        json.dumps(
            {
                "goal": "Exercise deterministic initialization",
                "lifecycle_stage": lifecycle,
                "risk_level": "medium",
            }
        ),
        encoding="utf-8",
    )
    return path


def _invoke(
    root: Path,
    tmp_path: Path,
    *,
    run_id: str,
    lifecycle: str = "active-development",
    extra: tuple[str, ...] = (),
) -> Any:
    checkpoints = tmp_path / f"{run_id}.sqlite3"
    return runner.invoke(
        app,
        [
            "init",
            "--path",
            str(root),
            "--run-id",
            run_id,
            "--checkpoints",
            str(checkpoints),
            "--answers",
            str(_answers(tmp_path, lifecycle=lifecycle)),
            "--confirm",
            "--json",
            *extra,
        ],
    )


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


def _capabilities(root: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        yaml.safe_load(
            (root / ".ai-project/capabilities.yaml").read_text(encoding="utf-8")
        ),
    )


def test_blank_dry_run_reports_decisions_without_writing_project(tmp_path: Path) -> None:
    root = build_scenario("blank", tmp_path / "blank").root
    before = _tree(root)

    result = _invoke(root, tmp_path, run_id="blank-dry", extra=("--dry-run",))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry-run"
    assert payload["applied_paths"] == []
    assert payload["inventory"]["capability_ids"] == []
    assert [item["requirement"] for item in payload["decisions"]] == [
        "quality.gates",
        "repository.exploration",
    ]
    assert all(item["status"] == "gap" for item in payload["decisions"])
    assert _tree(root) == before


def test_existing_python_apply_is_idempotent_and_doctor_is_healthy(tmp_path: Path) -> None:
    root = build_scenario("python-small", tmp_path / "python").root
    original = _tree(root)

    first = _invoke(root, tmp_path, run_id="python-first")
    assert first.exit_code == 0, first.output
    first_payload = json.loads(first.stdout)
    assert first_payload["status"] == "completed"
    assert original.items() <= _tree(root).items()
    assert ".ai-project/blueprint.yaml" in first_payload["applied_paths"]
    assert "AGENTS.md" in first_payload["applied_paths"]

    after_first = _tree(root)
    second = _invoke(root, tmp_path, run_id="python-second")
    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["applied_paths"] == []
    assert _tree(root) == after_first

    doctor = runner.invoke(app, ["doctor", "--path", str(root), "--json"])
    assert doctor.exit_code == 0, doctor.output
    assert json.loads(doctor.stdout) == {
        "findings": [],
        "schema_version": "1",
        "status": "healthy",
    }


def test_cancel_then_resume_completes_from_checkpoint(tmp_path: Path) -> None:
    root = build_scenario("no-skill", tmp_path / "resume").root
    checkpoint = tmp_path / "resume.sqlite3"
    paused = runner.invoke(
        app,
        [
            "init", "--path", str(root), "--run-id", "resume",
            "--checkpoints", str(checkpoint), "--json",
        ],
    )
    assert paused.exit_code == 0, paused.output
    assert json.loads(paused.stdout)["status"] == "paused"

    resumed = runner.invoke(
        app,
        [
            "init", "--path", str(root), "--run-id", "resume",
            "--checkpoints", str(checkpoint), "--answers", str(_answers(tmp_path)),
            "--confirm", "--resume", "--json",
        ],
    )
    assert resumed.exit_code == 0, resumed.output
    assert json.loads(resumed.stdout)["status"] == "completed"

    cancel_root = build_scenario("blank", tmp_path / "cancel").root
    cancelled = runner.invoke(
        app,
        [
            "init", "--path", str(cancel_root), "--run-id", "cancel",
            "--checkpoints", str(tmp_path / "cancel.sqlite3"), "--cancel", "--json",
        ],
    )
    assert cancelled.exit_code == 0, cancelled.output
    assert json.loads(cancelled.stdout)["status"] == "cancelled"
    assert not (cancel_root / ".ai-project").exists()


def test_apply_failure_rolls_back_repository_exactly(tmp_path: Path, monkeypatch: Any) -> None:
    root = build_scenario("python-small", tmp_path / "rollback").root
    before = _tree(root)
    calls = 0

    def fail_mid_apply(changeset: Any) -> Any:
        def replace(source: Path, target: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("injected writer failure")
            source.replace(target)

        return real_apply_changeset(changeset, replace=replace)

    monkeypatch.setattr("vibe.commands.init.apply_changeset", fail_mid_apply)
    result = _invoke(root, tmp_path, run_id="rollback")

    assert result.exit_code == 2
    assert "injected writer failure" in result.output
    assert _tree(root) == before


def test_capability_scenarios_emit_expected_inventory_and_decisions(tmp_path: Path) -> None:
    expectation_path = (
        Path(__file__).parents[1] / "scenarios" / "init" / "expected-decisions.json"
    )
    expectations = cast(
        dict[str, dict[str, list[str]]],
        json.loads(expectation_path.read_text(encoding="utf-8-sig")),
    )
    lifecycles = {"memory-provider": "exploration"}
    for name, expected in sorted(expectations.items()):
        lifecycle = lifecycles.get(name, "active-development")
        capability_ids = expected["capability_ids"]
        statuses = expected["statuses"]
        root = build_scenario(name, tmp_path / name).root
        result = _invoke(root, tmp_path, run_id=name, lifecycle=lifecycle)
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["inventory"]["capability_ids"] == capability_ids
        assert [item["status"] for item in payload["decisions"]] == statuses
        assert [item["status"] for item in _capabilities(root)["resolutions"]] == statuses


def test_conflicts_and_user_rejection_are_explicit_and_safe(tmp_path: Path) -> None:
    conflict_root = build_scenario("conflict", tmp_path / "conflict").root
    conflict = _invoke(conflict_root, tmp_path, run_id="conflict")
    assert conflict.exit_code == 0, conflict.output
    conflict_payload = json.loads(conflict.stdout)
    assert conflict_payload["inventory"]["capability_ids"] == []
    assert {item["code"] for item in conflict_payload["inventory"]["diagnostics"]} == {
        "duplicate_capability_id"
    }
    assert not any(item["status"] == "selected" for item in conflict_payload["decisions"])

    rejection_root = build_scenario("user-rejection", tmp_path / "rejection").root
    rejection = _invoke(rejection_root, tmp_path, run_id="rejection")
    assert rejection.exit_code == 0, rejection.output
    decisions = json.loads(rejection.stdout)["decisions"]
    assert [item["requirement"] for item in decisions] == [
        "automation.release",
        "quality.gates",
        "repository.exploration",
    ]
    assert decisions[0] == {
        "capability_id": None,
        "reason": "explicitly rejected by project policy",
        "requirement": "automation.release",
        "schema_version": "1",
        "status": "rejected",
    }
    assert all(item["status"] == "gap" for item in decisions[1:])

def _web_answers(tmp_path: Path, *, name: str) -> Path:
    path = tmp_path / f"{name}-answers.json"
    path.write_text(
        json.dumps(
            {
                "goal": "Build a blank web application",
                "lifecycle_stage": "active-development",
                "risk_level": "medium",
                "project_type": "web-application",
            }
        ),
        encoding="utf-8",
    )
    return path


def _install_fixture_codex_config(fixture_source: Path, monkeypatch: Any) -> None:
    user_codex = fixture_source / "user-codex"
    codex_home = Path(os.environ["CODEX_HOME"])
    shutil.copytree(user_codex, codex_home, dirs_exist_ok=True)
    executable = codex_home / "bin/chrome-devtools-mcp"
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{executable.parent}{os.pathsep}{os.environ.get('PATH', '')}")


def test_blank_web_init_selects_configured_chrome_devtools_mcp(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    built = build_scenario("blank-web-chrome", tmp_path / "web-chrome")
    _install_fixture_codex_config(built.fixture.source, monkeypatch)

    result = runner.invoke(
        app,
        [
            "init",
            "--path",
            str(built.root),
            "--run-id",
            "blank-web-chrome",
            "--checkpoints",
            str(tmp_path / "blank-web-chrome.sqlite3"),
            "--answers",
            str(_web_answers(tmp_path, name="blank-web-chrome")),
            "--confirm",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    browser = next(
        item
        for item in payload["resolution"]["resolutions"]
        if item["requirement"] == "browser.validation"
    )
    assert browser["status"] == "selected"
    assert browser["capability_id"] == "mcp.chrome-devtools"
    assert "mcp.chrome-devtools" in payload["inventory"]["capability_ids"]


def test_blank_web_init_reports_ranked_browser_gap_without_provider(
    tmp_path: Path,
) -> None:
    built = build_scenario("blank-web-no-browser", tmp_path / "web-no-browser")

    result = runner.invoke(
        app,
        [
            "init",
            "--path",
            str(built.root),
            "--run-id",
            "blank-web-no-browser",
            "--checkpoints",
            str(tmp_path / "blank-web-no-browser.sqlite3"),
            "--answers",
            str(_web_answers(tmp_path, name="blank-web-no-browser")),
            "--confirm",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    browser = next(
        item
        for item in payload["resolution"]["resolutions"]
        if item["requirement"] == "browser.validation"
    )
    assert browser["status"] == "gap"
    assert browser["capability_id"] is None
    assert [candidate["provider"] for candidate in browser["recommendation"]["candidates"]] == [
        "playwright",
        "chrome-devtools",
    ]
    assert all(
        candidate["permissions"] and candidate["why"]
        for candidate in browser["recommendation"]["candidates"]
    )
