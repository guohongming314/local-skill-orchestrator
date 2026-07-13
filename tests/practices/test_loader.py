from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from vibe.practices.loader import load_practice_pack, load_practice_packs

PACKS_ROOT = Path(__file__).parents[2] / "practice-packs"
EXPECTED_PACK_IDS = {
    "ai-application",
    "backend-api",
    "base-engineering",
    "cli-tool",
    "database-backed",
    "open-source-library",
    "security-sensitive",
    "web-application",
}


def test_all_initial_practice_packs_load_and_validate() -> None:
    packs = load_practice_packs(PACKS_ROOT)

    assert {pack.pack_id for pack in packs} == EXPECTED_PACK_IDS
    assert all(pack.requirements for pack in packs)
    assert all(pack.schema_version == "1" for pack in packs)
    assert {requirement.strength.value for pack in packs for requirement in pack.requirements} >= {
        "required",
        "recommended",
        "optional",
    }


def test_pack_schema_preserves_matching_exceptions_and_conflicts() -> None:
    pack = load_practice_pack(PACKS_ROOT / "security-sensitive" / "pack.yaml")

    assert pack.match.all_of
    assert pack.exceptions
    assert pack.conflicts
    assert all(requirement.rationale for requirement in pack.requirements)
    assert all(requirement.verification for requirement in pack.requirements)


def test_unknown_fields_fail_validation(tmp_path: Path) -> None:
    path = tmp_path / "pack.yaml"
    path.write_text(
        """schema_version: '1'
pack_id: invalid-pack
name: Invalid pack
description: Invalid pack fixture
priority: 1
match: {all_of: []}
requirements:
  - requirement_id: test
    capability: testing
    strength: required
    rationale: Testing is required
    verification: [pytest]
unknown_field: rejected
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="unknown_field"):
        load_practice_pack(path)


def test_unsupported_schema_versions_fail(tmp_path: Path) -> None:
    path = tmp_path / "pack.yaml"
    path.write_text(
        """schema_version: '2'
pack_id: future-pack
name: Future pack
description: Future pack fixture
priority: 1
match: {all_of: []}
requirements:
  - requirement_id: test
    capability: testing
    strength: required
    rationale: Testing is required
    verification: [pytest]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="unsupported schema_version"):
        load_practice_pack(path)


def test_directory_enumeration_order_does_not_change_normalized_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = list(PACKS_ROOT.glob("*/pack.yaml"))
    expected = load_practice_packs(PACKS_ROOT)
    original_glob = Path.glob

    def reverse_glob(path: Path, pattern: str):  # type: ignore[no-untyped-def]
        if path == PACKS_ROOT and pattern == "*/pack.yaml":
            return iter(reversed(paths))
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", reverse_glob)

    actual = load_practice_packs(PACKS_ROOT)

    assert actual == expected
    assert [pack.pack_id for pack in actual] == sorted(EXPECTED_PACK_IDS)
