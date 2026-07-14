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
        project_name="stack-drift-fixture",
        goal="Keep generated configuration aligned with the repository",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        repository_digest=inspect_repository(root).source_digest,
    )
    apply_changeset(_project_changeset(root, blueprint))


def test_stack_drift_offers_both_resolutions_and_applies_accept_reality(
    tmp_path: Path,
) -> None:
    initialized_project(tmp_path)
    policy = tmp_path / ".ai-project/policy.yaml"
    customized = policy.read_text(encoding="utf-8") + "# stack customization\n"
    policy.write_text(customized, encoding="utf-8")

    result = runner.invoke(app, ["reconcile", "--path", str(tmp_path)], input="accept\n")

    assert result.exit_code == 0, result.output
    assert "accept reality" in result.stdout.lower()
    assert "restore intent" in result.stdout.lower()
    assert result.stdout.count("ChangeSet ") >= 2
    assert policy.read_text(encoding="utf-8") == customized
    decisions = (tmp_path / ".ai-project/decisions.md").read_text(encoding="utf-8")
    assert "accept-reality" in decisions
    assert ".ai-project/policy.yaml" in decisions

    doctor = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
    assert doctor.exit_code == 0, doctor.output
    assert json.loads(doctor.stdout)["findings"] == []


def test_user_customization_is_only_overwritten_by_restore_intent(tmp_path: Path) -> None:
    initialized_project(tmp_path)
    policy = tmp_path / ".ai-project/policy.yaml"
    generated = policy.read_text(encoding="utf-8")
    policy.write_text(generated + "# user customization\n", encoding="utf-8")

    result = runner.invoke(app, ["reconcile", "--path", str(tmp_path)], input="restore\n")

    assert result.exit_code == 0, result.output
    assert policy.read_text(encoding="utf-8") == generated
    decisions = (tmp_path / ".ai-project/decisions.md").read_text(encoding="utf-8")
    assert "restore-intent" in decisions


def test_reconcile_dry_run_renders_all_previews_and_writes_nothing(tmp_path: Path) -> None:
    initialized_project(tmp_path)
    policy = tmp_path / ".ai-project/policy.yaml"
    policy.write_text(
        policy.read_text(encoding="utf-8") + "# user customization\n",
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    result = runner.invoke(app, ["reconcile", "--path", str(tmp_path), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "accept reality" in result.stdout.lower()
    assert "restore intent" in result.stdout.lower()
    assert result.stdout.count("ChangeSet ") >= 2
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
