from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

from vibe.cli import app
from vibe.migrations.registry import ArtifactKind, default_registry

runner = CliRunner()


def bump_v2(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(payload)
    migrated["schema_version"] = "2"
    return migrated


def register_generated_migration() -> None:
    default_registry.clear()
    default_registry.register(ArtifactKind.GENERATED_CONFIG, "1", "2", bump_v2)


def test_dry_run_shows_exact_yaml_diff_without_writing(tmp_path: Path) -> None:
    register_generated_migration()
    target = tmp_path / ".ai-project" / "policy.yaml"
    target.parent.mkdir()
    original = "schema_version: '1'\nname: demo\n"
    target.write_text(original, encoding="utf-8")

    result = runner.invoke(app, ["migrate", "--path", str(tmp_path), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert target.read_text(encoding="utf-8") == original
    assert "--- .ai-project/policy.yaml (before)" in result.output
    assert "+++ .ai-project/policy.yaml (after)" in result.output
    assert "-schema_version: '1'" in result.output
    assert "+schema_version: '2'" in result.output
    assert "--- .ai-project/migration-provenance.yaml (before)" in result.output
    assert "+++ .ai-project/migration-provenance.yaml (after)" in result.output


def test_apply_records_provenance_and_is_idempotent(tmp_path: Path) -> None:
    register_generated_migration()
    target = tmp_path / ".ai-project" / "policy.yaml"
    target.parent.mkdir()
    target.write_text("schema_version: '1'\nname: demo\n", encoding="utf-8")

    first = runner.invoke(app, ["migrate", "--path", str(tmp_path)])
    second = runner.invoke(app, ["migrate", "--path", str(tmp_path)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert yaml.safe_load(target.read_text())["schema_version"] == "2"
    history = yaml.safe_load(
        (tmp_path / ".ai-project" / "migration-provenance.yaml").read_text()
    )
    assert history["schema_version"] == "1"
    assert len(history["migrations"]) == 1
    record = history["migrations"][0]
    assert record["path"] == ".ai-project/policy.yaml"
    assert record["from_version"] == "1"
    assert record["to_version"] == "2"
    assert len(record["digest_before"]) == len(record["digest_after"]) == 64
    assert "No migrations required." in second.output
