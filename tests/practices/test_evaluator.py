from __future__ import annotations

from pathlib import Path

import pytest

from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot
from vibe.models.risk import RiskLevel
from vibe.practices.evaluator import PracticeConflictError, evaluate_practice_packs
from vibe.practices.loader import load_practice_packs
from vibe.practices.models import PracticePack, RequirementStrength
from vibe.resolver.requirements import RequirementOverride


def blueprint() -> Blueprint:
    return Blueprint(
        project_name="demo",
        goal="Build an API",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.HIGH,
        preferences={"testing": "test-first"},
        repository_digest="12345678",
    )


def snapshot(*facts: RepositoryFact) -> RepositorySnapshot:
    return RepositorySnapshot(
        root=Path("demo"),
        is_empty=False,
        facts=facts,
        source_digest="abcdefgh",
    )


def fact(key: str, value: str | list[str]) -> RepositoryFact:
    return RepositoryFact(
        key=key,
        value=value,
        confidence=FactConfidence.CONFIRMED,
        sources=("fixture",),
    )


def pack(
    pack_id: str,
    *,
    match_field: str = "project_type",
    match_value: str = "backend-api",
    capability: str = "testing",
    strength: str = "recommended",
    priority: int = 50,
    conflicts: list[dict[str, str]] | None = None,
    exceptions: list[dict[str, object]] | None = None,
) -> PracticePack:
    return PracticePack.model_validate(
        {
            "pack_id": pack_id,
            "name": pack_id,
            "description": f"{pack_id} practices",
            "priority": priority,
            "match": {
                "all_of": [
                    {"field": match_field, "operator": "equals", "value": match_value}
                ]
            },
            "requirements": [
                {
                    "requirement_id": f"{pack_id}-testing",
                    "capability": capability,
                    "strength": strength,
                    "rationale": f"Reason from {pack_id}",
                    "verification": [f"Verify {pack_id}"],
                }
            ],
            "conflicts": conflicts or [],
            "exceptions": exceptions or [],
        }
    )


def test_applicable_packs_merge_deterministically_with_provenance() -> None:
    base = pack(
        "base", match_field="project_name", match_value="demo", strength="recommended"
    )
    api = pack("api", strength="required", priority=70)
    repo = snapshot(fact("project_type", "backend-api"))

    forward = evaluate_practice_packs((base, api), blueprint(), repo)
    reverse = evaluate_practice_packs((api, base), blueprint(), repo)

    assert forward == reverse
    assert [item.capability for item in forward] == ["testing"]
    requirement = forward[0]
    assert requirement.strength is RequirementStrength.REQUIRED
    assert requirement.originating_packs == ("api", "base")
    assert requirement.reasons == ("Reason from api", "Reason from base")
    assert requirement.verification == ("Verify api", "Verify base")


def test_inapplicable_packs_never_enter_requirements() -> None:
    api = pack("api")
    web = pack("web", match_value="web-application", capability="browser-testing")

    requirements = evaluate_practice_packs(
        (web, api), blueprint(), snapshot(fact("project_type", "backend-api"))
    )

    assert [item.capability for item in requirements] == ["testing"]
    assert requirements[0].originating_packs == ("api",)


def test_user_overrides_win_over_pack_defaults() -> None:
    api = pack("api", capability="testing", strength="required")
    docs = pack("docs", capability="documentation", strength="required")
    repo = snapshot(fact("project_type", "backend-api"))

    requirements = evaluate_practice_packs(
        (api, docs),
        blueprint(),
        repo,
        overrides=(
            RequirementOverride(capability="testing", strength=RequirementStrength.OPTIONAL),
            RequirementOverride(capability="documentation", enabled=False),
        ),
    )

    assert [item.capability for item in requirements] == ["testing"]
    assert requirements[0].strength is RequirementStrength.OPTIONAL
    assert requirements[0].overridden is True


def test_matching_exception_suppresses_only_its_requirement() -> None:
    secure = pack(
        "secure",
        match_field="risk_level",
        match_value="high",
        capability="secret-scan",
        strength="required",
        exceptions=[
            {
                "exception_id": "active-development-exception",
                "when": {
                    "all_of": [
                        {
                            "field": "lifecycle_stage",
                            "operator": "equals",
                            "value": "active-development",
                        }
                    ]
                },
                "suppress_requirements": ["secure-testing"],
                "rationale": "Fixture exception",
            }
        ],
    )

    requirements = evaluate_practice_packs((secure,), blueprint(), snapshot())

    assert requirements == ()


def test_pack_conflicts_raise_with_actionable_provenance() -> None:
    first = pack(
        "first",
        conflicts=[
            {
                "pack_id": "second",
                "resolution": "error",
                "rationale": "The policies cannot be combined safely",
            }
        ],
    )
    second = pack("second")

    with pytest.raises(PracticeConflictError) as exc_info:
        evaluate_practice_packs(
            (second, first), blueprint(), snapshot(fact("project_type", "backend-api"))
        )

    message = str(exc_info.value)
    assert "first" in message
    assert "second" in message
    assert "cannot be combined safely" in message


def test_e18_requirements_follow_project_signals() -> None:
    packs = load_practice_packs(Path(__file__).parents[2] / "practice-packs")
    large_repo = snapshot(
        fact("is_monorepo", "true"),
        fact("repository_size", "large"),
    )
    production = blueprint().model_copy(
        update={"lifecycle_stage": LifecycleStage.PRODUCTION}
    )

    requirements = {
        item.capability: item
        for item in evaluate_practice_packs(packs, production, large_repo)
    }

    assert requirements["git.recovery"].strength is RequirementStrength.REQUIRED
    assert (
        requirements["code.relationship-analysis"].strength
        is RequirementStrength.RECOMMENDED
    )
    assert (
        requirements["project.continuity-memory"].strength
        is RequirementStrength.RECOMMENDED
    )
    assert requirements["release.rollback"].strength is RequirementStrength.REQUIRED


def test_e18_conditional_requirements_remain_unmatched() -> None:
    packs = load_practice_packs(Path(__file__).parents[2] / "practice-packs")
    small_repo = snapshot(
        fact("is_monorepo", "false"),
        fact("repository_size", "small"),
    )
    exploration = blueprint().model_copy(
        update={"lifecycle_stage": LifecycleStage.EXPLORATION}
    )

    capabilities = {
        item.capability
        for item in evaluate_practice_packs(packs, exploration, small_repo)
    }

    assert "git.recovery" in capabilities
    assert "code.relationship-analysis" not in capabilities
    assert "project.continuity-memory" not in capabilities
    assert "release.rollback" not in capabilities
    assert {"repository.exploration", "quality.gates"} <= capabilities


@pytest.mark.parametrize(
    "lifecycle",
    [
        LifecycleStage.ACTIVE_DEVELOPMENT,
        LifecycleStage.MAINTENANCE,
        LifecycleStage.PRODUCTION,
    ],
)
def test_development_loop_requirements_match_active_project_lifecycles(
    lifecycle: LifecycleStage,
) -> None:
    packs = load_practice_packs(Path(__file__).parents[2] / "practice-packs")
    project = blueprint().model_copy(update={"lifecycle_stage": lifecycle})

    requirements = {
        item.capability: item
        for item in evaluate_practice_packs(packs, project, snapshot())
    }

    assert requirements["development.design"].strength is RequirementStrength.RECOMMENDED
    assert requirements["code.optimization"].strength is RequirementStrength.RECOMMENDED


def test_development_loop_requirements_do_not_match_exploration() -> None:
    packs = load_practice_packs(Path(__file__).parents[2] / "practice-packs")
    project = blueprint().model_copy(
        update={"lifecycle_stage": LifecycleStage.EXPLORATION}
    )

    capabilities = {
        item.capability
        for item in evaluate_practice_packs(packs, project, snapshot())
    }

    assert "development.design" not in capabilities
    assert "code.optimization" not in capabilities
