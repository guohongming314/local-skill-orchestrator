from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path, PurePosixPath

from pydantic import Field, model_validator

from vibe.materialize.ownership import FileOwnership, OwnershipViolation
from vibe.models.base import VersionedModel

ABSENT_DIGEST = hashlib.sha256(b"<absent>").hexdigest()


class ChangeKind(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    UNCHANGED = "unchanged"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"


class ChangeProposal(VersionedModel):
    path: str = Field(min_length=1)
    desired_content: str | None
    ownership: FileOwnership
    source: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    sensitivity: Sensitivity = Sensitivity.NORMAL

    @model_validator(mode="after")
    def path_is_safe_and_normalized(self) -> ChangeProposal:
        if self.path != _normalize_relative_path(self.path):
            raise ValueError("path must be a normalized project-relative POSIX path")
        return self


class CommandProposal(VersionedModel):
    argv: tuple[str, ...] = Field(min_length=1)
    source: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def arguments_are_non_empty(self) -> CommandProposal:
        if any(not argument for argument in self.argv):
            raise ValueError("command arguments must be non-empty")
        return self


class CommandOperation(VersionedModel):
    argv: tuple[str, ...] = Field(min_length=1)
    source: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ChangeOperation(VersionedModel):
    path: str = Field(min_length=1)
    kind: ChangeKind
    ownership: FileOwnership
    before_content: str | None
    after_content: str | None
    before_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    sensitivity: Sensitivity = Sensitivity.NORMAL

    @model_validator(mode="after")
    def content_and_digests_are_consistent(self) -> ChangeOperation:
        if self.before_digest != _content_digest(self.before_content):
            raise ValueError("before_digest does not match before_content")
        if self.after_digest != _content_digest(self.after_content):
            raise ValueError("after_digest does not match after_content")
        expected = _change_kind(self.before_content, self.after_content)
        if self.kind is not expected:
            raise ValueError(f"kind must be {expected.value!r} for the supplied content")
        if self.ownership is FileOwnership.OBSERVED and self.kind is not ChangeKind.UNCHANGED:
            raise ValueError("observed files cannot carry write operations")
        return self


class ChangeSet(VersionedModel):
    root: Path
    operations: tuple[ChangeOperation, ...]
    commands: tuple[CommandOperation, ...] = ()
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def operations_are_unique_sorted_and_digest_matches(self) -> ChangeSet:
        paths = [operation.path for operation in self.operations]
        if paths != sorted(paths):
            raise ValueError("ChangeSet operations must be sorted by path")
        if len(paths) != len(set(paths)):
            raise ValueError("ChangeSet operation paths must be unique")
        if self.digest != _changeset_digest(self.operations, self.commands):
            raise ValueError("ChangeSet digest does not match operations")
        return self


def build_changeset(
    root: Path,
    proposals: tuple[ChangeProposal, ...],
    *,
    commands: tuple[CommandProposal, ...] = (),
) -> ChangeSet:
    """Inspect project state and produce a deterministic, write-free ChangeSet."""
    resolved_root = root.resolve()
    by_path: dict[str, ChangeProposal] = {}
    for proposal in proposals:
        if proposal.path in by_path:
            raise ValueError(f"duplicate change proposal path: {proposal.path}")
        by_path[proposal.path] = proposal
    operations = tuple(
        _build_operation(resolved_root, by_path[path]) for path in sorted(by_path)
    )
    command_operations = tuple(
        CommandOperation(argv=proposal.argv, source=proposal.source, reason=proposal.reason)
        for proposal in commands
    )
    return ChangeSet(
        root=resolved_root,
        operations=operations,
        commands=command_operations,
        digest=_changeset_digest(operations, command_operations),
    )


def render_dry_run(changeset: ChangeSet) -> str:
    """Render a stable human-readable preview without exposing file contents."""
    lines = [f"ChangeSet {changeset.digest}", f"Root: {changeset.root}"]
    if not changeset.operations and not changeset.commands:
        lines.append("No changes proposed.")
        return "\n".join(lines)
    for command in changeset.commands:
        lines.append(f"PENDING COMMAND {' '.join(command.argv)}")
        lines.append(f"  source: {command.source}")
        lines.append(f"  reason: {command.reason}")
    for operation in changeset.operations:
        lines.append(
            f"{operation.kind.value.upper()} {operation.path} "
            f"[{operation.ownership.value}; {operation.sensitivity.value}]"
        )
        lines.append(f"  source: {operation.source}")
        lines.append(f"  reason: {operation.reason}")
        lines.append(
            f"  digest: {operation.before_digest[:12]} -> {operation.after_digest[:12]}"
        )
    return "\n".join(lines)


def _build_operation(root: Path, proposal: ChangeProposal) -> ChangeOperation:
    target = (root / Path(*PurePosixPath(proposal.path).parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes project root: {proposal.path}")
    before = target.open("r", encoding="utf-8", newline="").read() if target.is_file() else None
    after = proposal.desired_content
    if proposal.ownership is FileOwnership.OBSERVED:
        after = before
    elif proposal.ownership is FileOwnership.MANAGED and before is not None and after is None:
        raise OwnershipViolation(f"managed files cannot be deleted: {proposal.path}")
    kind = _change_kind(before, after)
    return ChangeOperation(
        path=proposal.path,
        kind=kind,
        ownership=proposal.ownership,
        before_content=before,
        after_content=after,
        before_digest=_content_digest(before),
        after_digest=_content_digest(after),
        source=proposal.source,
        reason=proposal.reason,
        sensitivity=proposal.sensitivity,
    )


def _change_kind(before: str | None, after: str | None) -> ChangeKind:
    if before is None and after is not None:
        return ChangeKind.CREATE
    if before is not None and after is None:
        return ChangeKind.DELETE
    if before != after:
        return ChangeKind.UPDATE
    return ChangeKind.UNCHANGED


def _content_digest(content: str | None) -> str:
    if content is None:
        return ABSENT_DIGEST
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _changeset_digest(
    operations: tuple[ChangeOperation, ...], commands: tuple[CommandOperation, ...]
) -> str:
    payload = {
        "operations": [operation.model_dump(mode="json") for operation in operations],
        "commands": [command.model_dump(mode="json") for command in commands],
    }
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError("path must stay within the project root")
    if any(part in ("", ".") for part in candidate.parts):
        raise ValueError("path must be normalized")
    return candidate.as_posix()
