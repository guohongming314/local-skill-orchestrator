"""Atomic ChangeSet application with optimistic concurrency and rollback."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from vibe.materialize.changeset import (
    ABSENT_DIGEST,
    ChangeKind,
    ChangeOperation,
    ChangeSet,
    _content_digest,
)

Replace = Callable[[Path, Path], None]


class ConcurrentChangeError(RuntimeError):
    """The project changed after its ChangeSet was reviewed."""


class ApplyFailure(RuntimeError):
    """A write failed; the writer attempted a complete rollback."""


@dataclass(frozen=True)
class ApplyResult:
    changeset_digest: str
    applied_paths: tuple[str, ...]


def apply_changeset(changeset: ChangeSet, *, replace: Replace = os.replace) -> ApplyResult:
    """Verify, stage, and atomically apply a ChangeSet or restore the original tree."""
    root = changeset.root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    _verify_before_digests(root, changeset.operations)
    mutable = tuple(
        operation
        for operation in changeset.operations
        if operation.kind is not ChangeKind.UNCHANGED
    )
    if not mutable:
        return ApplyResult(changeset.digest, ())

    stage = Path(tempfile.mkdtemp(prefix=".vibe-stage-", dir=root))
    backup = Path(tempfile.mkdtemp(prefix=".vibe-backup-", dir=root))
    created_directories: set[Path] = set()
    backed_up: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        _stage_contents(stage, mutable)
        for operation in mutable:
            target = _target(root, operation.path)
            backup_target = backup / Path(*PurePosixPath(operation.path).parts)
            if target.exists():
                backup_target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup_target)
                backed_up.append((backup_target, target))
            if operation.after_content is not None:
                _ensure_parent(target.parent, root, created_directories)
                staged = stage / Path(*PurePosixPath(operation.path).parts)
                replace(staged, target)
                installed.append(target)
        shutil.rmtree(backup)
        shutil.rmtree(stage)
        return ApplyResult(changeset.digest, tuple(item.path for item in mutable))
    except Exception as error:
        rollback_errors = _rollback(installed, backed_up, created_directories)
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        detail = "rolled back"
        if rollback_errors:
            detail = f"rollback incomplete: {'; '.join(rollback_errors)}"
        raise ApplyFailure(f"ChangeSet apply failed and was {detail}: {error}") from error


def _verify_before_digests(root: Path, operations: tuple[ChangeOperation, ...]) -> None:
    conflicts: list[str] = []
    for operation in operations:
        target = _target(root, operation.path)
        if target.is_file():
            try:
                content = target.open("r", encoding="utf-8", newline="").read()
            except (OSError, UnicodeError) as error:
                raise ConcurrentChangeError(f"cannot verify {operation.path}: {error}") from error
            digest = _content_digest(content)
        elif target.exists():
            digest = "not-a-file"
        else:
            digest = ABSENT_DIGEST
        if digest != operation.before_digest:
            conflicts.append(operation.path)
    if conflicts:
        raise ConcurrentChangeError(
            "project changed since review; rebuild the ChangeSet for: " + ", ".join(conflicts)
        )


def _stage_contents(stage: Path, operations: tuple[ChangeOperation, ...]) -> None:
    for operation in operations:
        if operation.after_content is None:
            continue
        target = stage / Path(*PurePosixPath(operation.path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(operation.after_content, encoding="utf-8", newline="")


def _target(root: Path, relative: str) -> Path:
    target = (root / Path(*PurePosixPath(relative).parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes project root: {relative}")
    return target


def _ensure_parent(parent: Path, root: Path, created: set[Path]) -> None:
    missing: list[Path] = []
    candidate = parent
    while candidate != root and not candidate.exists():
        missing.append(candidate)
        candidate = candidate.parent
    parent.mkdir(parents=True, exist_ok=True)
    created.update(missing)


def _rollback(
    installed: list[Path],
    backed_up: list[tuple[Path, Path]],
    created_directories: set[Path],
) -> list[str]:
    errors: list[str] = []
    for target in reversed(installed):
        try:
            target.unlink(missing_ok=True)
        except OSError as error:
            errors.append(f"remove {target}: {error}")
    for source, target in reversed(backed_up):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        except OSError as error:
            errors.append(f"restore {target}: {error}")
    for directory in sorted(created_directories, key=lambda item: len(item.parts), reverse=True):
        with contextlib.suppress(OSError):
            directory.rmdir()
    return errors
