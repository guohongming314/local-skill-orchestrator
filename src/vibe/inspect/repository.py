"""Stable source snapshots for blank, non-Git, and Git repositories."""

from __future__ import annotations

import hashlib
from pathlib import Path

from vibe.inspect.git import inspect_git
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot


def inspect_repository(path: Path) -> RepositorySnapshot:
    """Inspect *path* without model interaction and return a deterministic snapshot."""
    resolved = path.resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    git = inspect_git(resolved)
    root = git.root if git is not None else resolved
    files = tuple(_source_files(root))
    facts: tuple[RepositoryFact, ...] = ()
    if git is not None:
        facts = (
            RepositoryFact(
                key="git.branch",
                value=git.branch,
                confidence=(
                    FactConfidence.CONFIRMED
                    if git.branch is not None
                    else FactConfidence.UNKNOWN
                ),
                sources=("git symbolic-ref --short HEAD",),
            ),
            RepositoryFact(
                key="git.untracked",
                value=list(git.untracked),
                confidence=FactConfidence.CONFIRMED,
                sources=("git status --porcelain=v1",),
            ),
        )
    return RepositorySnapshot(
        root=root,
        is_empty=not files,
        git_root=None if git is None else git.root,
        head=None if git is None else git.head,
        dirty=None if git is None else git.dirty,
        facts=facts,
        source_digest=_source_digest(root, files),
    )


def _source_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(root).parts
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _source_digest(root: Path, files: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
