from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe.cli import app
from vibe.commands.init import _project_changeset
from vibe.inspect.repository import inspect_repository
from vibe.materialize.writer import apply_changeset
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.risk import RiskLevel

runner = CliRunner()


def initialized_project(root: Path) -> None:
    blueprint = Blueprint(
        project_name="diff-cli-fixture",
        goal="Preview exact pending changes",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        repository_digest=inspect_repository(root).source_digest,
    )
    apply_changeset(_project_changeset(root, blueprint))


def test_diff_is_empty_and_stable_for_current_project(tmp_path: Path) -> None:
    initialized_project(tmp_path)

    first = runner.invoke(app, ["diff", "--path", str(tmp_path), "--json"])
    second = runner.invoke(app, ["diff", "--path", str(tmp_path), "--json"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout) == {
        "changes": [],
        "schema_version": "1",
        "status": "current",
    }


def test_diff_reports_exact_managed_change_without_writing(tmp_path: Path) -> None:
    initialized_project(tmp_path)
    policy = tmp_path / ".ai-project/policy.yaml"
    policy.write_text(policy.read_text(encoding="utf-8") + "# manual edit\n", encoding="utf-8")
    before = policy.read_bytes()

    first = runner.invoke(app, ["diff", "--path", str(tmp_path), "--json"])
    second = runner.invoke(app, ["diff", "--path", str(tmp_path), "--json"])

    assert first.exit_code == 1
    assert second.exit_code == 1
    assert first.stdout == second.stdout
    assert policy.read_bytes() == before
    output = json.loads(first.stdout)
    assert output["status"] == "changes-pending"
    assert output["changes"] == [
        {
            "actual_digest": output["changes"][0]["actual_digest"],
            "expected_digest": output["changes"][0]["expected_digest"],
            "kind": "update",
            "path": ".ai-project/policy.yaml",
        }
    ]
    assert "manual edit" not in first.stdout


def test_diff_human_output_names_changed_path_and_performs_no_write(tmp_path: Path) -> None:
    initialized_project(tmp_path)
    policy = tmp_path / ".ai-project/policy.yaml"
    policy.unlink()

    result = runner.invoke(app, ["diff", "--path", str(tmp_path)])

    assert result.exit_code == 1
    assert "CREATE .ai-project/policy.yaml" in result.stdout
    assert not policy.exists()
