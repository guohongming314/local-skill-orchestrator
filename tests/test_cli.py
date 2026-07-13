from pathlib import Path

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


def test_schema_export(tmp_path: Path) -> None:
    result = runner.invoke(app, ["schema", "export", "--output", str(tmp_path)])

    assert result.exit_code == 0
    assert len(list(tmp_path.glob("*.schema.json"))) == 6
    assert '"title": "Blueprint"' in (tmp_path / "blueprint.schema.json").read_text()
