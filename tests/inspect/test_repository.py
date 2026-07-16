from __future__ import annotations

import subprocess
from pathlib import Path

from vibe.inspect.repository import inspect_repository
from vibe.models.repository import FactConfidence


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)


def initialize(path: Path) -> None:
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.invalid")


def test_blank_directory_is_distinguished_from_non_git_source(tmp_path: Path) -> None:
    blank = tmp_path / "blank"
    blank.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("print('hello')\n", encoding="utf-8")

    blank_snapshot = inspect_repository(blank)
    source_snapshot = inspect_repository(source)

    assert blank_snapshot.is_empty is True
    assert blank_snapshot.git_root is None
    assert source_snapshot.is_empty is False
    assert source_snapshot.git_root is None
    assert blank_snapshot.source_digest != source_snapshot.source_digest


def test_git_metadata_does_not_make_an_unborn_repository_non_empty(tmp_path: Path) -> None:
    initialize(tmp_path)

    snapshot = inspect_repository(tmp_path)

    assert snapshot.is_empty is True
    assert snapshot.git_root == tmp_path.resolve()
    assert snapshot.head is None
    assert snapshot.dirty is False


def test_nested_input_resolves_to_git_root_and_emits_git_facts(tmp_path: Path) -> None:
    initialize(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    git(tmp_path, "add", "pyproject.toml")
    git(tmp_path, "commit", "-m", "initial")
    nested = tmp_path / "src"
    nested.mkdir()
    (nested / "module.py").write_text("value = 1\n", encoding="utf-8")

    snapshot = inspect_repository(nested)

    assert snapshot.root == tmp_path.resolve()
    assert snapshot.git_root == tmp_path.resolve()
    assert snapshot.dirty is True
    facts = {fact.key: fact for fact in snapshot.facts}
    assert facts["git.branch"].value == "main"
    assert facts["git.branch"].confidence is FactConfidence.CONFIRMED
    assert facts["git.untracked"].value == ["src/"]


def test_repeated_scans_are_identical_until_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    file = source / "main.py"
    file.write_text("print(1)\n", encoding="utf-8")

    first = inspect_repository(source)
    second = inspect_repository(source)
    file.write_text("print(2)\n", encoding="utf-8")
    changed = inspect_repository(source)

    assert first == second
    assert first.source_digest != changed.source_digest


def test_agent_skills_do_not_change_business_source_digest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    application = source / "main.py"
    application.write_text("print(1)\n", encoding="utf-8")
    before = inspect_repository(source)
    skill = source / ".agents/skills/formatter/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("skill version one\n", encoding="utf-8")
    with_skill = inspect_repository(source)
    skill.write_text("skill version two\n", encoding="utf-8")
    changed_skill = inspect_repository(source)
    application.write_text("print(2)\n", encoding="utf-8")
    changed_source = inspect_repository(source)

    assert before.source_digest == with_skill.source_digest == changed_skill.source_digest
    assert changed_source.source_digest != changed_skill.source_digest
