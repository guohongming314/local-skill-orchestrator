from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.materialize.test_templates import inputs
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
    metadata = yaml.safe_load((skill_root / "agents/openai.yaml").read_text(encoding="utf-8"))
    assert metadata["interface"]["display_name"] == "Local Skill Orchestrator"
    assert "$bootstrap-skill" in metadata["interface"]["default_prompt"]


def test_bootstrap_skill_keeps_guidance_separate_from_cli_policy() -> None:
    document = (ROOT / "bootstrap-skill/SKILL.md").read_text(encoding="utf-8")

    for command in ("vibe inspect", "vibe init --dry-run", "vibe init", "vibe doctor"):
        assert command in document
    assert "CLI owns deterministic" in document
    assert "Do not bypass approval" in document


def test_generated_project_skill_still_passes_structural_validation(tmp_path: Path) -> None:
    rendered = render_project_configuration(*inputs())
    for relative, content in rendered.as_dict().items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    result = _scan(
        tmp_path / ".agents/skills/project-development",
        CapabilityScope.PROJECT,
    )
    assert result.manifest.capability_id == "skill.project-development"
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
