"""Transactional project-local installation of approved remote capabilities."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import Field, model_validator

from vibe.inventory.service import InventoryResult
from vibe.materialize.changeset import (
    ChangeProposal,
    ChangeSet,
    CommandProposal,
    build_changeset,
)
from vibe.materialize.ownership import FileOwnership
from vibe.materialize.writer import apply_changeset
from vibe.models.base import VersionedModel
from vibe.remote.models import PermissionLevel, RemoteCandidate

_LOCK_PATH = ".ai-project/capabilities.lock"
_AUDIT_PATH = ".ai-project/audit.log"


class ApprovalRequiredError(RuntimeError):
    """The requested install has not passed its explicit approval gate."""


class InstallVerificationError(RuntimeError):
    """The staged capability did not resolve after installation."""


class InstallFile(VersionedModel):
    path: str = Field(min_length=1)
    content: str


class InstallPackage(VersionedModel):
    files: tuple[InstallFile, ...]
    commands: tuple[tuple[str, ...], ...] = ()

    @model_validator(mode="after")
    def paths_are_unique(self) -> InstallPackage:
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("install package file paths must be unique")
        return self


class InstallPlan(VersionedModel):
    root: Path
    candidate: RemoteCandidate
    package: InstallPackage
    changeset: ChangeSet
    required_approval: PermissionLevel


@dataclass(frozen=True)
class InstallResult:
    inventory: InventoryResult
    applied_paths: tuple[str, ...]


InventoryScan = Callable[[Path], InventoryResult]


def build_install_plan(
    root: Path, candidate: RemoteCandidate, package: InstallPackage
) -> InstallPlan:
    """Build a deterministic project-local install plan without writing anything."""
    provenance = candidate.provenance
    if candidate.version is None or provenance is None or not provenance.digest_verified:
        raise ValueError("install candidates require a pinned version and verified digest")
    if provenance.permission_level is PermissionLevel.L4:
        raise ValueError("L4 candidates are blocked and cannot be installed")

    provider = _provider_entry(candidate)
    lock_content = _render_lock(
        root,
        provider,
        inventory_digest=provenance.digest.removeprefix("sha256:"),
    )
    audit_content = _append_audit(root, candidate, status="planned")
    proposals = (
        *(
            ChangeProposal(
                path=item.path,
                desired_content=item.content,
                ownership=FileOwnership.OWNED,
                source=candidate.candidate_ref,
                reason=f"install approved remote capability {candidate.name}",
            )
            for item in package.files
        ),
        ChangeProposal(
            path=_LOCK_PATH,
            desired_content=lock_content,
            ownership=FileOwnership.OWNED,
            source=candidate.candidate_ref,
            reason="pin installed capability provenance",
        ),
        ChangeProposal(
            path=_AUDIT_PATH,
            desired_content=audit_content,
            ownership=FileOwnership.OWNED,
            source=candidate.candidate_ref,
            reason="record capability install transaction",
        ),
    )
    commands = tuple(
        CommandProposal(
            argv=argv,
            source=candidate.candidate_ref,
            reason=f"install {candidate.name}",
        )
        for argv in package.commands
    )
    resolved_root = root.resolve()
    return InstallPlan(
        root=resolved_root,
        candidate=candidate,
        package=package,
        changeset=build_changeset(resolved_root, proposals, commands=commands),
        required_approval=provenance.permission_level,
    )


def execute_install(
    plan: InstallPlan, *, approved: bool, inventory_scan: InventoryScan
) -> InstallResult:
    """Stage, install, verify, and atomically commit, leaving no failure residue."""
    if not approved:
        raise ApprovalRequiredError(
            f"explicit {plan.required_approval.value} approval is required before installation"
        )

    root = plan.root.resolve()
    with tempfile.TemporaryDirectory(prefix="vibe-install-") as temporary:
        staged_root = Path(temporary) / "project"
        shutil.copytree(root, staged_root, ignore=shutil.ignore_patterns(".git"))
        staged_changeset = _retarget_changeset(plan.changeset, staged_root)
        apply_changeset(staged_changeset)
        inventory = inventory_scan(staged_root)
        provider_id = _provider_id(plan.candidate)
        if not any(item.manifest.capability_id == provider_id for item in inventory.capabilities):
            raise InstallVerificationError(
                f"installed capability {provider_id!r} did not resolve in inventory"
            )

        lock_path = staged_root / _LOCK_PATH
        lock_path.write_text(
            _render_lock(
                staged_root,
                _provider_entry(plan.candidate),
                inventory_digest=inventory.inventory_digest,
            ),
            encoding="utf-8",
        )
        (staged_root / _AUDIT_PATH).write_text(
            _append_audit(staged_root, plan.candidate, status="installed"),
            encoding="utf-8",
        )
        commit = _build_tree_commit(root, staged_root, plan.candidate.candidate_ref)
        applied = apply_changeset(commit)
    return InstallResult(inventory=inventory, applied_paths=applied.applied_paths)


def _retarget_changeset(changeset: ChangeSet, root: Path) -> ChangeSet:
    proposals = tuple(
        ChangeProposal(
            path=operation.path,
            desired_content=operation.after_content,
            ownership=operation.ownership,
            source=operation.source,
            reason=operation.reason,
            sensitivity=operation.sensitivity,
        )
        for operation in changeset.operations
    )
    commands = tuple(
        CommandProposal(argv=item.argv, source=item.source, reason=item.reason)
        for item in changeset.commands
    )
    return build_changeset(root, proposals, commands=commands)


def _build_tree_commit(root: Path, staged: Path, source: str) -> ChangeSet:
    original = _byte_tree(root)
    desired = _byte_tree(staged)
    changed = [
        path
        for path in sorted(original.keys() | desired.keys())
        if original.get(path) != desired.get(path)
    ]
    proposals = tuple(
        ChangeProposal(
            path=path,
            desired_content=desired[path].decode("utf-8") if path in desired else None,
            ownership=FileOwnership.OWNED,
            source=source,
            reason="commit verified install transaction",
        )
        for path in changed
    )
    return build_changeset(root, proposals)


def _byte_tree(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(root).parts:
            continue
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _provider_id(candidate: RemoteCandidate) -> str:
    prefixes = {
        "agent-skill": "skill",
        "cli-tool": "cli",
        "mcp-server": "mcp",
        "plugin": "plugin",
    }
    return f"{prefixes[candidate.kind.value]}.{candidate.name}"


def _provider_entry(candidate: RemoteCandidate) -> dict[str, object]:
    provenance = candidate.provenance
    if provenance is None:
        raise ValueError("candidate provenance is required")
    return {
        "provider_id": _provider_id(candidate),
        "kind": candidate.kind.value,
        "scope": "project",
        "source": provenance.source,
        "version": candidate.version,
        "content_digest": provenance.digest,
        "publisher": provenance.publisher,
        "source_verified": provenance.source_verified,
        "publisher_verified": provenance.publisher_verified,
        "publisher_verification": provenance.publisher_verification.value,
        "digest_verified": provenance.digest_verified,
        "permission_level": provenance.permission_level.value,
    }


def _render_lock(root: Path, provider: dict[str, object], *, inventory_digest: str) -> str:
    providers: list[dict[str, object]] = []
    lock_path = root / _LOCK_PATH
    if lock_path.is_file():
        try:
            loaded = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            loaded = None
        if isinstance(loaded, dict) and isinstance(loaded.get("providers"), list):
            providers = [item for item in loaded["providers"] if isinstance(item, dict)]
    providers = [item for item in providers if item.get("provider_id") != provider["provider_id"]]
    providers.append(provider)
    payload = {
        "schema_version": "1",
        "inventory_digest": inventory_digest,
        "providers": sorted(providers, key=lambda item: str(item.get("provider_id", ""))),
    }
    return yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)


def _append_audit(root: Path, candidate: RemoteCandidate, *, status: str) -> str:
    audit_path = root / _AUDIT_PATH
    existing = audit_path.read_text(encoding="utf-8") if audit_path.is_file() else ""
    event = {
        "candidate_ref": candidate.candidate_ref,
        "digest": candidate.provenance.digest if candidate.provenance else None,
        "event": "capability.install",
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "version": candidate.version,
    }
    return existing + json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
