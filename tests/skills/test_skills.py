from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.materialize.test_templates import inputs, requirements
from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.adapters.base import AdapterScanResult
from vibe.materialize.templates import render_project_configuration
from vibe.models.capability import CapabilityScope

ROOT = Path(__file__).parents[2]


pytestmark = pytest.mark.validation


def _scan(skill_root: Path, scope: CapabilityScope = CapabilityScope.USER) -> AdapterScanResult:
    adapter = AgentSkillAdapter(roots=(SkillRoot(skill_root.parent, scope),))
    discoveries = adapter.discover()
    assert len(discoveries) == 1
    return adapter.scan(discoveries[0])


def test_bootstrap_skill_and_openai_metadata_are_structurally_valid() -> None:
    skill_root = ROOT / "bootstrap-skill"
    result = _scan(skill_root)

    assert result.manifest.capability_id == "skill.bootstrap-skill"
    assert result.verification.verified
    assert "dependency:agents/openai.yaml" in result.verification.details
    metadata = yaml.safe_load((skill_root / "agents/openai.yaml").read_text(encoding="utf-8"))
    assert set(metadata) == {"interface", "policy"}
    assert metadata["interface"]["display_name"] == "Local Skill Orchestrator"
    default_prompt = metadata["interface"]["default_prompt"]
    assert "$bootstrap-skill" in default_prompt
    assert "conversation" in default_prompt
    assert metadata["policy"]["allow_implicit_invocation"] is True


def test_bootstrap_skill_keeps_cli_internal_to_the_codex_workflow() -> None:
    document = (ROOT / "bootstrap-skill/SKILL.md").read_text(encoding="utf-8")

    for statement in (
        "The user stays in the current Codex conversation",
        "Use deterministic project capability tools internally",
        "The internal `vibe` executable must be available",
        "Do not ask the user to run `vibe` commands",
        "Do not start another Codex process",
        "Ask only repository-unknown high-impact questions",
        "abstract capability needs and gaps",
        "project-local installation or permission changes",
        "Codex-native Skill discovery",
    ):
        assert statement in document

    for user_facing_command in (
        "Run `vibe inspect",
        "Run `vibe init",
        "Run `vibe doctor",
        "Run vibe inspect",
        "Run vibe init",
        "Run vibe doctor",
    ):
        assert user_facing_command not in document


def test_bootstrap_skill_preserves_capability_governance_boundaries() -> None:
    document = (ROOT / "bootstrap-skill/SKILL.md").read_text(encoding="utf-8")

    assert "Inventory never executes discovered capabilities" in document
    assert "Do not bypass approval" in document
    assert "automatically perform read-only remote discovery" in document
    assert "Project-local installation is the default" in document


def test_bootstrap_skill_separates_discovery_from_installation_approval() -> None:
    document = (ROOT / "bootstrap-skill/SKILL.md").read_text(encoding="utf-8")

    for requirement in (
        "static candidate leads",
        "Do not ask the user to approve discovery",
        "Do not ask the user to select trusted search sources",
        "source-unavailable",
        "search-failed",
        "no-results",
        "all-filtered",
        "candidates-found",
        "separate installation approval",
        "missing cache",
    ):
        assert requirement in document
    assert "request discovery approval" not in document


def test_bootstrap_skill_requires_adaptive_recommendations_before_changeset() -> None:
    document = (ROOT / "bootstrap-skill/SKILL.md").read_text(encoding="utf-8")

    assert "Do not infer an unanswered permission as denied" in document
    assert "Ask only when the answer can change" in document
    assert (
        "Do not request ChangeSet approval while recommendation readiness is false"
        in document
    )


def test_generated_project_skill_still_passes_structural_validation(tmp_path: Path) -> None:
    blueprint, plan, inventory = inputs()
    rendered = render_project_configuration(
        blueprint, plan, inventory, requirements=requirements()
    )
    for relative, content in rendered.as_dict().items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    result = _scan(
        tmp_path / ".agents/skills/project-capability-manager",
        CapabilityScope.PROJECT,
    )
    assert result.manifest.capability_id == "skill.project-capability-manager"
    assert result.manifest.codex_skill is not None
    assert result.manifest.codex_skill.allow_implicit_invocation is True
    assert result.verification.verified


def test_release_checklist_covers_required_manual_reviews_and_gates() -> None:
    document = (ROOT / "docs/release-checklist.md").read_text(encoding="utf-8")

    for requirement in (
        "Security",
        "Privacy",
        "Rollback",
        "Manual core-flow review",
        "task-routing evaluation thresholds",
        "uv build",
        "git diff --check",
    ):
        assert requirement in document


def test_migration_guide_explains_missing_capability_manager_flow() -> None:
    document = (
        ROOT / "docs/migration/codex-native-capability-governance.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(document.split())

    for requirement in (
        "project-capability-manager",
        "missing or unhealthy",
        "inspect, recommend, install, or reconcile",
        "user approval",
        "continues the original task",
        "same conversation",
    ):
        assert requirement in normalized
