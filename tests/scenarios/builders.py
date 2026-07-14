"""Deterministic builders for reusable end-to-end scenario projects."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FIXTURES = Path(__file__).with_name("fixtures")
SCENARIO_NAMES = tuple(
    sorted(path.name for path in _FIXTURES.iterdir() if path.is_dir())
)


@dataclass(frozen=True)
class ScenarioFixture:
    name: str
    description: str
    capabilities: tuple[str, ...]
    conflicts: tuple[str, ...]
    expected_facts: dict[str, Any]
    source: Path


@dataclass(frozen=True)
class BuiltScenario:
    root: Path
    fixture: ScenarioFixture
    snapshot: dict[str, Any]


def load_scenario(name: str) -> ScenarioFixture:
    """Load one versioned fixture description without building it."""
    source = _FIXTURES / name
    if name not in SCENARIO_NAMES:
        raise KeyError(f"unknown scenario fixture: {name}")
    payload = json.loads((source / "scenario.json").read_text(encoding="utf-8"))
    expected = json.loads(
        (source / "expected-facts.json").read_text(encoding="utf-8")
    )
    return ScenarioFixture(
        name=name,
        description=payload["description"],
        capabilities=tuple(payload["capabilities"]),
        conflicts=tuple(payload["conflicts"]),
        expected_facts=expected,
        source=source,
    )


def build_scenario(name: str, target: Path) -> BuiltScenario:
    """Build a fixture into an empty target using only local versioned files."""
    fixture = load_scenario(name)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"scenario target is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    project = fixture.source / "project"
    for source in sorted(project.rglob("*"), key=lambda item: item.as_posix()):
        relative = source.relative_to(project)
        destination = target / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    metadata = target / ".scenario"
    metadata.mkdir(exist_ok=True)
    (metadata / "scenario.json").write_text(
        json.dumps(
            {
                "name": fixture.name,
                "description": fixture.description,
                "capabilities": list(fixture.capabilities),
                "conflicts": list(fixture.conflicts),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (metadata / "expected-facts.json").write_text(
        json.dumps(fixture.expected_facts, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return BuiltScenario(
        root=target,
        fixture=fixture,
        snapshot=dict(fixture.expected_facts),
    )
