from __future__ import annotations

import json
from pathlib import Path

from tests.scenarios.builders import SCENARIO_NAMES, build_scenario, load_scenario

EXPECTED_SCENARIOS = {
    "blank",
    "blank-web-chrome",
    "blank-web-no-browser",
    "codegraph",
    "conflict",
    "large-monorepo",
    "memory-provider",
    "no-skill",
    "node-small",
    "python-small",
    "user-rejection",
}


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_catalog_covers_representative_repository_and_capability_environments() -> None:
    assert set(SCENARIO_NAMES) == EXPECTED_SCENARIOS


def test_each_fixture_documents_capabilities_conflicts_and_expected_facts() -> None:
    for name in SCENARIO_NAMES:
        fixture = load_scenario(name)

        assert fixture.description
        assert fixture.capabilities is not None
        assert fixture.conflicts is not None
        assert fixture.expected_facts
        assert fixture.expected_facts["scenario.name"] == name


def test_builds_are_byte_identical_in_isolated_directories(tmp_path: Path) -> None:
    for name in SCENARIO_NAMES:
        first = build_scenario(name, tmp_path / "first" / name)
        second = build_scenario(name, tmp_path / "second" / name)

        assert tree_bytes(first.root) == tree_bytes(second.root)
        assert first.fixture == second.fixture
        assert first.snapshot == second.snapshot


def test_built_snapshot_matches_versioned_expected_snapshot(tmp_path: Path) -> None:
    for name in SCENARIO_NAMES:
        built = build_scenario(name, tmp_path / name)
        expected = json.loads(
            (built.root / ".scenario/expected-facts.json").read_text(encoding="utf-8")
        )

        assert built.snapshot == expected
        assert expected == built.fixture.expected_facts


def test_fixtures_contain_no_secret_or_network_dependency_markers() -> None:
    forbidden = ("api_key", "password", "secret=", "https://", "http://")

    for name in SCENARIO_NAMES:
        fixture = load_scenario(name)
        for path in fixture.source.rglob("*"):
            if path.is_file():
                content = path.read_text(encoding="utf-8")
                assert not any(marker in content.lower() for marker in forbidden)
