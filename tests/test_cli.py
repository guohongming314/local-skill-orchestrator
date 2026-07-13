from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import metadata, resources
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibe import __version__
from vibe.cli import app

runner = CliRunner()


def test_help_exposes_product_purpose() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "project-local AI development capabilities" in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


@pytest.mark.parametrize(
    "command",
    [
        [sys.executable, "-m", "vibe", "--version"],
        [shutil.which("vibe") or "vibe", "--version"],
    ],
    ids=["python-module", "console-script"],
)
def test_external_cli_entry_points_expose_package_version(command: list[str]) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == __version__


def test_distribution_metadata_declares_cli_and_typed_package() -> None:
    entry_points = metadata.entry_points(group="console_scripts")
    vibe_entry_point = next(
        entry_point for entry_point in entry_points if entry_point.name == "vibe"
    )

    assert vibe_entry_point.value == "vibe.cli:main"
    assert resources.files("vibe").joinpath("py.typed").is_file()


def test_schema_export(tmp_path: Path) -> None:
    result = runner.invoke(app, ["schema", "export", "--output", str(tmp_path)])

    assert result.exit_code == 0
    assert len(list(tmp_path.glob("*.schema.json"))) == 7
    assert '"title": "Blueprint"' in (tmp_path / "blueprint.schema.json").read_text()
