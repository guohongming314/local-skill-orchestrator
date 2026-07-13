from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe.cli import app
from vibe.models.repository import FactConfidence, RepositorySnapshot

runner = CliRunner()


def create_repository(root: Path) -> None:
    (root / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
    )
    (root / "AGENTS.md").write_text("root rules\n", encoding="utf-8")
    nested = root / "packages" / "api"
    nested.mkdir(parents=True)
    (nested / "CLAUDE.md").write_text("api rules\n", encoding="utf-8")
    cursor = root / ".cursor" / "rules"
    cursor.mkdir(parents=True)
    (cursor / "python.mdc").write_text("python rules\n", encoding="utf-8")


def test_json_output_validates_and_is_byte_stable(tmp_path: Path) -> None:
    create_repository(tmp_path)

    first = runner.invoke(app, ["inspect", "--path", str(tmp_path), "--json"])
    second = runner.invoke(app, ["inspect", "--path", str(tmp_path), "--json"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert first.stdout == second.stdout
    snapshot = RepositorySnapshot.model_validate_json(first.stdout)
    facts = {fact.key: fact for fact in snapshot.facts}
    assert facts["instructions.files"].value == [
        ".cursor/rules/python.mdc (scope: .)",
        "AGENTS.md (scope: .)",
        "packages/api/CLAUDE.md (scope: packages/api)",
    ]
    assert facts["commands.test"].value == ["vitest run"]


def test_human_output_distinguishes_confidence_levels_and_scopes(tmp_path: Path) -> None:
    create_repository(tmp_path)

    result = runner.invoke(app, ["inspect", "--path", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "[confirmed]" in result.stdout
    assert "[inferred]" in result.stdout
    assert "[unknown]" in result.stdout
    assert "packages/api/CLAUDE.md (scope: packages/api)" in result.stdout


def test_instruction_files_have_confirmed_file_provenance(tmp_path: Path) -> None:
    create_repository(tmp_path)

    result = runner.invoke(app, ["inspect", "--path", str(tmp_path), "--json"])
    snapshot = RepositorySnapshot.model_validate_json(result.stdout)
    instruction = next(fact for fact in snapshot.facts if fact.key == "instructions.files")

    assert instruction.confidence is FactConfidence.CONFIRMED
    assert instruction.sources == (
        ".cursor/rules/python.mdc",
        "AGENTS.md",
        "packages/api/CLAUDE.md",
    )


def test_malformed_manifest_reports_actionable_scan_error(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{broken", encoding="utf-8")

    result = runner.invoke(app, ["inspect", "--path", str(tmp_path), "--json"])

    assert result.exit_code == 2
    assert "inspection failed" in result.stderr
    assert "package.json" in result.stderr
