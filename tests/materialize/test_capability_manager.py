from __future__ import annotations

from tests.materialize.test_templates import inputs
from vibe.materialize.capability_manager import (
    render_agents_guidance,
    render_capability_manager_references,
    render_capability_manager_skill,
)


def test_skill_is_narrow_capability_governance_not_a_task_router() -> None:
    blueprint, _, _ = inputs()
    document = render_capability_manager_skill(blueprint)
    frontmatter = document.split("---", 2)[1]

    for phrase in (
        "missing or unhealthy capability or dependency",
        "install, replace, update, remove, or manage",
        "Do not use for ordinary task classification",
        "existing capabilities are sufficient",
    ):
        assert phrase in frontmatter

    for phrase in (
        "cannot complete a task with the current skills or tools",
        "missing or unhealthy",
        "asks to manage capabilities",
        "Do not use this Skill for ordinary task classification",
        "Codex-native Skill discovery",
        "explain the capability gap",
        "approval",
        "install, replace, update, disable, or remove",
        "Doctor",
        "Never start another Codex",
        "never delegate task execution to `vibe run`",
    ):
        assert phrase in document
    assert "project-development" not in document


def test_references_capture_approved_providers_gaps_and_governance() -> None:
    _, plan, inventory = inputs()
    references = render_capability_manager_references(plan, inventory)

    assert set(references) == {
        "references/capability-gaps.md",
        "references/quality-and-governance.md",
    }
    gaps = references["references/capability-gaps.md"]
    assert "`cli.pytest`" in gaps
    assert "release-automation" in gaps
    governance = references["references/quality-and-governance.md"]
    assert "explicit approval" in governance
    assert "Doctor" in governance


def test_agents_guidance_is_concise_and_preserves_codex_ownership() -> None:
    guidance = render_agents_guidance()

    assert len(guidance.encode("utf-8")) < 2048
    assert "Codex-native Skill discovery" in guidance
    assert "missing, unhealthy, or explicitly managed" in guidance
    assert "every project operation" not in guidance
    assert "vibe run" not in guidance
