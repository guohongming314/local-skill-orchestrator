from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe.cli import app
from vibe.commands.schema import SCHEMA_MODELS

runner = CliRunner()


def export_schemas(output: Path) -> None:
    result = runner.invoke(app, ["schema", "export", "--output", str(output)])
    assert result.exit_code == 0, result.output


def test_schema_export_contains_every_top_level_contract(tmp_path: Path) -> None:
    output = tmp_path / "schemas"

    export_schemas(output)

    assert set(SCHEMA_MODELS) == {
        "blueprint",
        "capability-manifest",
        "context-capsule",
        "repository-snapshot",
        "resolution-plan",
        "risk",
        "task-plan",
    }
    assert {path.stem.removesuffix(".schema") for path in output.glob("*.json")} == set(
        SCHEMA_MODELS
    )
    for path in output.glob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["properties"]["schema_version"]["default"] == "1"


def test_repeated_schema_exports_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    export_schemas(first)
    export_schemas(second)

    assert {
        path.name: path.read_bytes() for path in sorted(first.glob("*.json"))
    } == {path.name: path.read_bytes() for path in sorted(second.glob("*.json"))}