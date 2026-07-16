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
            if path.is_file() and _is_source_path(path.relative_to(root))
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _source_digest(root: Path, files: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = _source_content(root, path)
        if relative == b"AGENTS.md" and not content.strip():
            continue
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


_MANAGED_BEGIN = b"<!-- local-skill-orchestrator:begin -->"
_MANAGED_END = b"<!-- local-skill-orchestrator:end -->"


def _is_source_path(relative: Path) -> bool:
    parts = relative.parts
    if ".git" in parts or (parts and parts[0] == ".ai-project"):
        return False
    if parts[:2] == (".agents", "skills"):
        return False
    return not relative.name.startswith(".vibe-init-checkpoints.sqlite3")


def _source_content(root: Path, path: Path) -> bytes:
    content = path.read_bytes()
    if path.relative_to(root).as_posix() != "AGENTS.md":
        return content
    newline = b"\r\n" if b"\r\n" in content else b"\n"
    begin = content.find(_MANAGED_BEGIN)
    end = content.find(_MANAGED_END)
    if begin < 0 and end < 0:
        return content.rstrip(b"\r\n") + newline
    if begin < 0 or end < begin or content.find(_MANAGED_BEGIN, begin + 1) >= 0:
        return content
    end += len(_MANAGED_END)
    if content[end : end + 2] == b"\r\n":
        end += 2
    elif content[end : end + 1] in (b"\r", b"\n"):
        end += 1
    unmanaged = content[:begin].rstrip(b"\r\n") + content[end:]
    return unmanaged.rstrip(b"\r\n") + newline
