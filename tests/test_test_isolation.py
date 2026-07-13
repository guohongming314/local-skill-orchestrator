from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.helpers import CommandRunner, FrozenClock


def test_isolated_home_redirects_user_and_tool_directories(isolated_home: Path) -> None:
    assert Path.home() == isolated_home
    assert Path(os.environ["HOME"]) == isolated_home
    assert Path(os.environ["USERPROFILE"]) == isolated_home
    assert Path(os.environ["XDG_CONFIG_HOME"]).is_relative_to(isolated_home)
    assert Path(os.environ["XDG_DATA_HOME"]).is_relative_to(isolated_home)
    assert Path(os.environ["XDG_CACHE_HOME"]).is_relative_to(isolated_home)
    assert Path(os.environ["CODEX_HOME"]).is_relative_to(isolated_home)


def test_project_root_is_an_empty_directory(project_root: Path) -> None:
    assert project_root.is_dir()
    assert list(project_root.iterdir()) == []


def test_command_runner_uses_isolated_environment(
    command_runner: CommandRunner,
    isolated_home: Path,
) -> None:
    result = command_runner.run_python("import os; print(os.environ['HOME'])")

    assert result.returncode == 0
    assert Path(result.stdout.strip()) == isolated_home


def test_deterministic_clock_has_fixed_utc_time(deterministic_clock: FrozenClock) -> None:
    assert deterministic_clock.now() == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_environment_changes_are_restored_by_fixture_teardown(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    original_environment: dict[str, str | None],
) -> None:
    assert Path(os.environ["HOME"]) == isolated_home

    monkeypatch.undo()

    for name, original_value in original_environment.items():
        assert os.environ.get(name) == original_value
