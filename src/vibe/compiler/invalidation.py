"""Shared typed reasons for invalidating generated project context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InvalidationKind(StrEnum):
    """Stable categories shared by Doctor and future Context Capsules."""

    GIT_HEAD_CHANGED = "git-head-changed"
    TECHNOLOGY_STACK_CHANGED = "technology-stack-changed"
    REPOSITORY_SOURCE_CHANGED = "repository-source-changed"
    LOCKFILE_CHANGED = "lockfile-changed"
    MANAGED_FILE_CHANGED = "managed-file-changed"


@dataclass(frozen=True)
class InvalidationReason:
    """One content-free explanation of why project context may be stale."""

    kind: InvalidationKind
    sources: tuple[str, ...]
    invalidates_configuration: bool
    expected_digest: str | None = None
    actual_digest: str | None = None
