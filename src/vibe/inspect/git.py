"""Git state discovery using stable porcelain output."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitState:
    """Confirmed Git identity and working-tree state for one repository."""

    root: Path
    head: str | None
    branch: str | None
    dirty: bool
    untracked: tuple[str, ...]


def inspect_git(path: Path) -> GitState | None:
    """Return Git state for *path*, or ``None`` when it is outside a work tree."""
    resolved = path.resolve()
    root_result = _git(resolved, "rev-parse", "--show-toplevel")
    if root_result.returncode != 0:
        return None
    root = Path(root_result.stdout.strip()).resolve()
    head_result = _git(root, "rev-parse", "--verify", "HEAD")
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    branch_result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    status = _git(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=normal",
    )
    if status.returncode != 0:
        raise RuntimeError(f"git status failed for {root}: {status.stderr.strip()}")
    entries = tuple(entry for entry in status.stdout.split("\0") if entry)
    untracked = tuple(sorted(entry[3:] for entry in entries if entry.startswith("?? ")))
    return GitState(
        root=root,
        head=head,
        branch=branch,
        dirty=bool(entries),
        untracked=untracked,
    )


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
