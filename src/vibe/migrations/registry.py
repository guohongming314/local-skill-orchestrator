"""Pure, deterministic schema migration registry and artifact discovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from vibe.models.decisions import DecisionSource, ProjectDecisions

Migration = Callable[[dict[str, Any]], dict[str, Any]]


class ArtifactKind(StrEnum):
    PRACTICE_PACK = "practice-pack"
    CAPABILITY_MANIFEST = "capability-manifest"
    GENERATED_CONFIG = "generated-config"


class MigrationError(ValueError):
    """Base error for an artifact that cannot be migrated safely."""


class UnknownSchemaVersionError(MigrationError):
    """Raised when an artifact is newer than the migrations understood locally."""


class MissingMigrationError(MigrationError):
    """Raised when no contiguous path exists from an old version to the latest."""


@dataclass(frozen=True)
class MigrationProvenance:
    from_version: str
    to_version: str
    digest_before: str
    digest_after: str


@dataclass(frozen=True)
class MigrationResult:
    payload: dict[str, Any]
    from_version: str
    to_version: str
    provenance: tuple[MigrationProvenance, ...]


@dataclass(frozen=True)
class Artifact:
    path: Path
    relative_path: str
    kind: ArtifactKind
    payload: dict[str, Any]


class MigrationRegistry:
    """Register contiguous N-to-N+1 pure functions by artifact kind."""

    def __init__(self) -> None:
        self._migrations: dict[ArtifactKind, dict[str, tuple[str, Migration]]] = {}

    def clear(self) -> None:
        self._migrations.clear()

    def register(
        self,
        kind: ArtifactKind,
        from_version: str,
        to_version: str,
        migration: Migration,
    ) -> None:
        source = _version_number(from_version)
        target = _version_number(to_version)
        if target != source + 1:
            raise ValueError("migrations must advance exactly one schema version")
        migrations = self._migrations.setdefault(kind, {})
        if from_version in migrations:
            raise ValueError(f"duplicate migration for {kind.value} schema {from_version}")
        migrations[from_version] = (to_version, migration)

    def latest_version(self, kind: ArtifactKind) -> str | None:
        migrations = self._migrations.get(kind, {})
        if not migrations:
            return None
        return str(max(_version_number(target) for target, _ in migrations.values()))

    def migrate(
        self, kind: ArtifactKind, payload: Mapping[str, Any]
    ) -> MigrationResult:
        current_payload = deepcopy(dict(payload))
        original = _schema_version(current_payload)
        current = original
        latest = self.latest_version(kind)
        if latest is None:
            return MigrationResult(current_payload, original, original, ())
        if _version_number(current) > _version_number(latest):
            raise UnknownSchemaVersionError(
                f"{kind.value} has future schema_version {current!r}; "
                f"latest supported is {latest!r}"
            )

        provenance: list[MigrationProvenance] = []
        while current != latest:
            step = self._migrations.get(kind, {}).get(current)
            if step is None:
                raise MissingMigrationError(
                    f"no {kind.value} migration from schema_version {current!r} to {latest!r}"
                )
            to_version, migration = step
            before = _payload_digest(current_payload)
            migrated = migration(deepcopy(current_payload))
            if not isinstance(migrated, dict):
                raise MigrationError("migration must return a YAML mapping")
            if _schema_version(migrated) != to_version:
                raise MigrationError(
                    f"migration {current}->{to_version} returned schema_version "
                    f"{migrated.get('schema_version')!r}"
                )
            after = _payload_digest(migrated)
            provenance.append(MigrationProvenance(current, to_version, before, after))
            current_payload = migrated
            current = to_version
        return MigrationResult(current_payload, original, current, tuple(provenance))


def discover_artifacts(root: Path) -> tuple[Artifact, ...]:
    """Discover supported YAML artifacts in deterministic project-relative order."""
    resolved = root.resolve()
    candidates = set(resolved.glob("practice-packs/*/pack.yaml"))
    ai_project = resolved / ".ai-project"
    if ai_project.is_dir():
        candidates.update(ai_project.glob("*.yaml"))
    candidates.update(resolved.glob("**/capability-manifest.yaml"))
    candidates.update(resolved.glob("**/manifest.yaml"))

    artifacts: list[Artifact] = []
    for path in sorted(candidates):
        relative = path.relative_to(resolved).as_posix()
        if relative == ".ai-project/migration-provenance.yaml" or not path.is_file():
            continue
        payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            continue
        kind = _artifact_kind(relative, payload)
        if kind is None:
            continue
        artifacts.append(Artifact(path, relative, kind, dict(payload)))
    return tuple(artifacts)


def dump_yaml(payload: Mapping[str, Any]) -> str:
    return yaml.safe_dump(dict(payload), sort_keys=False, allow_unicode=True)


def _artifact_kind(relative: str, payload: Mapping[str, Any]) -> ArtifactKind | None:
    if relative.startswith("practice-packs/") and relative.endswith("/pack.yaml"):
        return ArtifactKind.PRACTICE_PACK
    if relative.startswith(".ai-project/"):
        return ArtifactKind.GENERATED_CONFIG
    if "capability_id" in payload and "kind" in payload and "provides" in payload:
        return ArtifactKind.CAPABILITY_MANIFEST
    return None


def _schema_version(payload: Mapping[str, Any]) -> str:
    version = payload.get("schema_version")
    if not isinstance(version, str) or not version.isdigit():
        raise MigrationError("artifact schema_version must be a numeric string")
    return version


def _version_number(version: str) -> int:
    if not version.isdigit():
        raise ValueError("schema versions must be numeric strings")
    return int(version)


def _payload_digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def version_bump(to_version: str) -> Migration:
    """Build a pure migration for a schema revision with no structural changes."""
    _version_number(to_version)

    def migrate(payload: dict[str, Any]) -> dict[str, Any]:
        migrated = deepcopy(payload)
        migrated["schema_version"] = to_version
        return migrated

    return migrate


default_registry = MigrationRegistry()


def migrate_artifact(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Apply artifact-specific compatibility migrations within a schema version."""
    migrated = deepcopy(dict(payload))
    if kind != "blueprint":
        raise ValueError(f"unsupported artifact migration kind: {kind!r}")
    _schema_version(migrated)
    if "decisions" in migrated:
        return migrated
    decisions = ProjectDecisions().model_dump(mode="json")
    for field in (
        "read_project",
        "write_project",
        "execute_command",
        "write_outside_project",
        "access_secrets",
        "network_policy",
    ):
        decisions[field]["provenance"] = {
            "schema_version": "1",
            "source": DecisionSource.MIGRATION.value,
            "reference": "legacy-blueprint-without-decisions",
        }
    migrated["decisions"] = decisions
    return migrated
