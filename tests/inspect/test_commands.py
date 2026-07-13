from __future__ import annotations

import json
from pathlib import Path

from vibe.inspect.commands import inspect_commands
from vibe.models.repository import FactConfidence, RepositoryFact


def facts(root: Path) -> dict[str, RepositoryFact]:
    return {fact.key: fact for fact in inspect_commands(root)}


def test_package_scripts_are_extracted_without_execution(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    package = {
        "scripts": {
            "build": "python -c \"open('must-not-exist','w').close()\"",
            "start": "node server.js",
            "test": "vitest run",
            "lint": "eslint .",
            "format": "prettier --write .",
            "typecheck": "tsc --noEmit",
        }
    }
    (tmp_path / "package.json").write_text(json.dumps(package), encoding="utf-8")

    result = facts(tmp_path)

    assert marker.exists() is False
    assert result["commands.build"].value == [package["scripts"]["build"]]
    assert result["commands.test"].value == ["vitest run"]
    assert result["commands.typecheck"].sources == (
        "package.json:scripts.typecheck",
    )
    assert all(fact.confidence is FactConfidence.CONFIRMED for fact in result.values())


def test_makefile_and_package_script_conflict_is_explicit(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
    )
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n", encoding="utf-8")

    test = facts(tmp_path)["commands.test"]

    assert test.value == ["make test", "vitest run"]
    assert test.confidence is FactConfidence.CONFLICT
    assert test.sources == ("Makefile:test", "package.json:scripts.test")


def test_missing_command_categories_remain_unknown(tmp_path: Path) -> None:
    result = facts(tmp_path)

    assert set(result) == {
        "commands.build",
        "commands.format",
        "commands.lint",
        "commands.start",
        "commands.test",
        "commands.typecheck",
    }
    assert all(fact.value is None for fact in result.values())
    assert all(fact.confidence is FactConfidence.UNKNOWN for fact in result.values())
