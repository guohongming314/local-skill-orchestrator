from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from vibe.migrations.registry import (
    ArtifactKind,
    MigrationRegistry,
    UnknownSchemaVersionError,
    migrate_artifact,
)

FIXTURES = Path(__file__).parent / "fixtures"


def bump(to_version: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def migration(payload: dict[str, Any]) -> dict[str, Any]:
        migrated = deepcopy(payload)
        migrated["schema_version"] = to_version
        return migrated

    return migration


def test_v1_pack_fixture_migrates_to_v2_and_validates() -> None:
    registry = MigrationRegistry()
    registry.register(ArtifactKind.PRACTICE_PACK, "1", "2", bump("2"))
    source = yaml.safe_load((FIXTURES / "pack-v1.yaml").read_text())
    expected = yaml.safe_load((FIXTURES / "pack-v2.yaml").read_text())

    result = registry.migrate(ArtifactKind.PRACTICE_PACK, source)

    assert result.payload == expected
    assert result.from_version == "1"
    assert result.to_version == "2"
    assert len(result.provenance) == 1
    assert result.provenance[0].digest_before != result.provenance[0].digest_after


def test_unknown_future_version_fails_loudly() -> None:
    registry = MigrationRegistry()
    registry.register(ArtifactKind.CAPABILITY_MANIFEST, "1", "2", bump("2"))

    with pytest.raises(UnknownSchemaVersionError, match="future schema_version '3'"):
        registry.migrate(ArtifactKind.CAPABILITY_MANIFEST, {"schema_version": "3"})


def test_migration_is_idempotent() -> None:
    registry = MigrationRegistry()
    registry.register(ArtifactKind.GENERATED_CONFIG, "1", "2", bump("2"))
    first = registry.migrate(ArtifactKind.GENERATED_CONFIG, {"schema_version": "1"})

    second = registry.migrate(ArtifactKind.GENERATED_CONFIG, first.payload)

    assert second.payload == first.payload
    assert second.provenance == ()
    assert second.from_version == second.to_version == "2"


def test_chained_migrations_match_direct_v3_fixture() -> None:
    registry = MigrationRegistry()
    registry.register(ArtifactKind.PRACTICE_PACK, "1", "2", bump("2"))

    def add_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        migrated: dict[str, Any] = bump("3")(payload)
        migrated["metadata"] = {"format": "practice-pack"}
        return migrated

    registry.register(ArtifactKind.PRACTICE_PACK, "2", "3", add_metadata)

    result = registry.migrate(
        ArtifactKind.PRACTICE_PACK,
        {"schema_version": "1", "pack_id": "base-engineering"},
    )

    assert result.payload == {
        "schema_version": "3",
        "pack_id": "base-engineering",
        "metadata": {"format": "practice-pack"},
    }
    assert [(item.from_version, item.to_version) for item in result.provenance] == [
        ("1", "2"),
        ("2", "3"),
    ]


def test_legacy_blueprint_migrates_missing_decisions_to_unknown() -> None:
    migrated = migrate_artifact(
        "blueprint",
        {
            "schema_version": "1",
            "project_name": "legacy",
            "goal": "Maintain a project",
            "lifecycle_stage": "maintenance",
            "risk_level": "medium",
            "repository_digest": "01234567",
        },
    )

    assert migrated["decisions"]["network_policy"]["value"] == "unknown"
    assert migrated["decisions"]["network_policy"]["provenance"]["source"] == "migration"
    assert migrated["decisions"]["network_policy"]["provenance"]["reference"] == (
        "legacy-blueprint-without-decisions"
    )
