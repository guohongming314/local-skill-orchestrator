from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.helpers import CommandRunner, FrozenClock

ENVIRONMENT_VARIABLES = (
    "HOME",
    "USERPROFILE",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "CODEX_HOME",
    "CLAUDE_CONFIG_DIR",
)


@pytest.fixture(scope="session")
def original_environment() -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in ENVIRONMENT_VARIABLES}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    home = tmp_path / "home"
    config = home / ".config"
    data = home / ".local" / "share"
    cache = home / ".cache"
    codex = home / ".codex"
    claude = home / ".claude"

    for directory in (home, config, data, cache, codex, claude):
        directory.mkdir(parents=True, exist_ok=True)

    variables = {
        "HOME": home,
        "USERPROFILE": home,
        "XDG_CONFIG_HOME": config,
        "XDG_DATA_HOME": data,
        "XDG_CACHE_HOME": cache,
        "CODEX_HOME": codex,
        "CLAUDE_CONFIG_DIR": claude,
    }
    for name, value in variables.items():
        monkeypatch.setenv(name, str(value))

    yield home


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.fixture
def command_runner(project_root: Path) -> CommandRunner:
    return CommandRunner(cwd=project_root, environment=os.environ.copy())


@pytest.fixture
def deterministic_clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
