from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tests.commands.test_install import _bundle
from vibe.cli import app

runner = CliRunner()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def test_install_uninstall_round_trip_restores_byte_identical_repository(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path / "candidate.json")
    (tmp_path / ".ai-project").mkdir()
    (tmp_path / ".ai-project" / "audit.log").write_bytes(b"pre-existing-audit\n")
    (tmp_path / "README.md").write_bytes(b"original repository\n")
    before = _snapshot(tmp_path)

    installed = runner.invoke(
        app,
        [
            "install",
            "browser-testing",
            "--path",
            str(tmp_path),
            "--candidate-file",
            str(bundle),
            "--approve",
        ],
    )
    assert installed.exit_code == 0, installed.stdout

    uninstalled = runner.invoke(
        app,
        ["uninstall", "browser-testing", "--path", str(tmp_path)],
    )

    assert uninstalled.exit_code == 0, uninstalled.stdout
    assert _snapshot(tmp_path) == before
