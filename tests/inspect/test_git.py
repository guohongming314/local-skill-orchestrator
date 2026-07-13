from __future__ import annotations

import subprocess
from pathlib import Path

from vibe.inspect.git import inspect_git


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def initialize(path: Path) -> None:
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.invalid")


def test_non_git_directory_has_no_git_state(tmp_path: Path) -> None:
    assert inspect_git(tmp_path) is None


def test_clean_git_repository_reports_root_head_and_branch(tmp_path: Path) -> None:
    initialize(tmp_path)
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-m", "initial")
    nested = tmp_path / "src" / "package"
    nested.mkdir(parents=True)

    state = inspect_git(nested)

    assert state is not None
    assert state.root == tmp_path.resolve()
    assert state.head == git(tmp_path, "rev-parse", "HEAD")
    assert state.branch == "main"
    assert state.dirty is False
    assert state.untracked == ()


def test_dirty_git_repository_reports_changes_and_sorted_untracked_files(tmp_path: Path) -> None:
    initialize(tmp_path)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("first\n", encoding="utf-8")
    git(tmp_path, "add", "tracked.txt")
    git(tmp_path, "commit", "-m", "initial")
    tracked.write_text("changed\n", encoding="utf-8")
    (tmp_path / "z.txt").write_text("z\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")

    state = inspect_git(tmp_path)

    assert state is not None
    assert state.dirty is True
    assert state.untracked == ("a.txt", "z.txt")
