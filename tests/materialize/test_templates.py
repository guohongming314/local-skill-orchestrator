from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.adapters.base import (
    AdapterProvenance,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.inventory.service import InventoryResult
from vibe.materialize.templates import (
    CapabilityLock,
    CapabilityLockEntry,
    RenderedProject,
    render_project_configuration,
    validate_rendered_yaml,
)
from vibe.models.blueprint import Blueprint, LifecycleStage, ProjectConstraint
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)
from vibe.models.codex_skill import CodexSkillMetadata, SkillToolDependency
from vibe.models.resolution import (
    CapabilityRecommendation,
    CapabilityResolution,
    RecommendationCandidate,
    ResolutionPlan,
    ResolutionStatus,
)
from vibe.models.risk import RiskLevel
from vibe.practices.models import RequirementStrength
from vibe.resolver.requirements import AbstractCapabilityRequirement


def test_capability_lock_rejects_duplicate_provider_ids() -> None:
    provider = CapabilityLockEntry(
        provider_id="hook.project",
        kind="hook",
        scope="project",
        source=".codex/hooks.json",
        content_digest="digest-value",
    )

    with pytest.raises(ValidationError):
        CapabilityLock(inventory_digest="inventory-digest", providers=(provider, provider))


FIXTURE = Path(__file__).parents[1] / "fixtures" / "generated" / "project.snapshot"


def capability(
    capability_id: str,
    *,
    provides: tuple[str, ...],
    digest: str,
    kind: CapabilityKind = CapabilityKind.CLI_TOOL,
    codex_skill: CodexSkillMetadata | None = None,
) -> AdapterScanResult:
    manifest = CapabilityManifest(
        capability_id=capability_id,
        name=capability_id,
        kind=kind,
        scope=CapabilityScope.USER,
        source=f"local:{capability_id}",
        provides=provides,
        permissions=frozenset({Permission.READ_PROJECT}),
        version="1.2.3",
        content_digest=digest,
        verified=True,
        codex_skill=codex_skill,
    )
    return AdapterScanResult(
        manifest=manifest,
        provenance=AdapterProvenance("fixture", capability_id),
        verification=AdapterVerification(True, ("fixture verified",)),
    )


def requirements() -> tuple[AbstractCapabilityRequirement, ...]:
    return (
        AbstractCapabilityRequirement(
            capability="quality.gates",
            strength=RequirementStrength.REQUIRED,
            originating_packs=("quality",),
            originating_requirements=("quality-gates",),
            reasons=("The project requires deterministic quality checks.",),
            verification=("Run the configured quality gate before completion.",),
        ),
        AbstractCapabilityRequirement(
            capability="testing",
            strength=RequirementStrength.RECOMMENDED,
            originating_packs=("development",),
            originating_requirements=("test-runner",),
            reasons=("The project preference is test-first development.",),
            verification=("Run focused tests for changed behavior.",),
        ),
    )


def inputs() -> tuple[Blueprint, ResolutionPlan, InventoryResult]:
    blueprint = Blueprint(
        project_name="demo-project",
        goal="Build a reliable command-line service",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        constraints=(ProjectConstraint(name="python", value="3.12", locked=True),),
        preferences={"testing": "test-first", "parallelism": 1},
        repository_digest="repository-digest",
    )
    inventory = InventoryResult(
        capabilities=(
            capability(
                "cli.pytest",
                provides=("quality.gates", "testing"),
                digest="pytest-content-digest",
            ),
            capability(
                "mcp.search",
                provides=("semantic-search",),
                digest="search-content-digest",
                kind=CapabilityKind.MCP,
            ),
            capability(
                "skill.test-guide",
                provides=("testing",),
                digest="skill-content-digest",
                kind=CapabilityKind.SKILL,
                codex_skill=CodexSkillMetadata(
                    allow_implicit_invocation=False,
                    tool_dependencies=(
                        SkillToolDependency(dependency_type="mcp", value="filesystem"),
                    ),
                ),
            ),
        ),
        diagnostics=(),
        inventory_digest="inventory-digest",
    )
    plan = ResolutionPlan(
        blueprint_digest="blueprint-digest",
        inventory_digest=inventory.inventory_digest,
        resolutions=(
            CapabilityResolution(
                requirement="quality.gates",
                status=ResolutionStatus.SELECTED,
                capability_id="cli.pytest",
                reason="selected deterministic local provider",
            ),
            CapabilityResolution(
                requirement="semantic-search",
                status=ResolutionStatus.REJECTED,
                capability_id="mcp.search",
                reason="higher permission provider rejected",
            ),
            CapabilityResolution(
                requirement="testing",
                status=ResolutionStatus.SELECTED,
                capability_id="skill.test-guide",
                reason="selected project testing guidance",
            ),
            CapabilityResolution(
                requirement="release-automation",
                status=ResolutionStatus.GAP,
                reason="no local provider",
            ),
        ),
    )
    return blueprint, plan, inventory


def render_inputs() -> RenderedProject:
    blueprint, plan, inventory = inputs()
    return render_project_configuration(blueprint, plan, inventory, requirements=requirements())


def test_renders_complete_project_configuration_and_all_yaml_validates() -> None:
    rendered = render_inputs()
    files = rendered.as_dict()

    assert set(files) == {
        ".ai-project/blueprint.yaml",
        ".ai-project/capabilities.yaml",
        ".ai-project/capabilities.lock",
        ".ai-project/capability-requirements.yaml",
        ".ai-project/policy.yaml",
        ".ai-project/decisions.md",
        ".ai-project/quality-gates.md",
        ".ai-project/workflows.yaml",
        ".ai-project/task-policies.yaml",
        ".ai-project/capability-usage.yaml",
        ".agents/skills/project-capability-manager/SKILL.md",
        ".agents/skills/project-capability-manager/agents/openai.yaml",
        ".agents/skills/project-capability-manager/references/capability-gaps.md",
        ".agents/skills/project-capability-manager/references/governance-commands.md",
        ".agents/skills/project-capability-manager/references/quality-and-governance.md",
    }
    validate_rendered_yaml(rendered)
    Blueprint.model_validate(yaml.safe_load(files[".ai-project/blueprint.yaml"]))


def test_lockfile_pins_selected_provider_identity_and_content_digest() -> None:
    files = render_inputs().as_dict()

    lock = yaml.safe_load(files[".ai-project/capabilities.lock"])

    assert lock["schema_version"] == "1"
    assert lock["inventory_digest"] == "inventory-digest"
    assert lock["providers"][0] == {
        "provider_id": "cli.pytest",
        "kind": "cli-tool",
        "scope": "user",
        "source": "local:cli.pytest",
        "version": "1.2.3",
        "content_digest": "pytest-content-digest",
    }
    assert "codex_skill" not in lock["providers"][0]
    assert lock["providers"][1]["provider_id"] == "skill.test-guide"
    assert lock["providers"][1]["codex_skill"] == {
        "allow_implicit_invocation": False,
        "tool_dependencies": [{"dependency_type": "mcp", "value": "filesystem"}],
    }
    assert "mcp.search" not in files[".ai-project/capabilities.lock"]


def test_requirement_artifact_preserves_abstract_evaluation_without_provider_binding() -> None:
    payload = yaml.safe_load(render_inputs().as_dict()[".ai-project/capability-requirements.yaml"])

    quality_gate = next(
        item for item in payload["requirements"] if item["capability"] == "quality.gates"
    )
    assert quality_gate["strength"] == "required"
    assert quality_gate["reasons"] == ["The project requires deterministic quality checks."]
    assert quality_gate["verification"] == ["Run the configured quality gate before completion."]
    assert quality_gate["selected_provider"] is None


def test_rendered_snapshot_is_byte_stable() -> None:
    first = render_inputs().snapshot_bytes()
    second = render_inputs().snapshot_bytes()

    assert first == second
    assert first == FIXTURE.read_bytes()


def test_generated_project_skill_passes_local_structural_validation(tmp_path: Path) -> None:
    rendered = render_inputs()
    for relative_path, content in rendered.as_dict().items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    skill_root = tmp_path / ".agents" / "skills"
    adapter = AgentSkillAdapter(roots=(SkillRoot(skill_root, CapabilityScope.PROJECT),))
    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.capability_id == "skill.project-capability-manager"
    assert result.manifest.version == "1.0.0"
    assert result.verification.verified
    assert result.verification.details == (
        "dependency:agents/openai.yaml",
        "dependency:references/capability-gaps.md",
        "dependency:references/governance-commands.md",
        "dependency:references/quality-and-governance.md",
    )


def test_template_sources_are_versioned_and_do_not_contain_project_values() -> None:
    template_root = Path(__file__).parents[2] / "templates" / "project-capability-manager"

    skill_template = (template_root / "SKILL.md.tmpl").read_text(encoding="utf-8")

    assert "template-version: 1" in skill_template
    assert "demo-project" not in skill_template


def test_gap_recommendations_render_in_decisions() -> None:
    blueprint, plan, inventory = inputs()
    browser_gap = CapabilityResolution(
        requirement="browser.validation",
        status=ResolutionStatus.GAP,
        reason="no local provider",
        recommendation=CapabilityRecommendation(
            why="Validate user-visible browser behavior",
            candidates=(
                RecommendationCandidate(
                    kind=CapabilityKind.CLI_TOOL,
                    provider="playwright",
                    permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
                    why="Prefer deterministic browser validation",
                    strength=RequirementStrength.RECOMMENDED,
                ),
                RecommendationCandidate(
                    kind=CapabilityKind.MCP,
                    provider="chrome-devtools",
                    permissions=(
                        Permission.READ_PROJECT,
                        Permission.EXECUTE_COMMAND,
                        Permission.NETWORK,
                    ),
                    why="Use browser MCP only for interactive browser control",
                    strength=RequirementStrength.OPTIONAL,
                ),
            ),
        ),
    )
    plan = plan.model_copy(update={"resolutions": (*plan.resolutions, browser_gap)})

    decisions = render_project_configuration(
        blueprint, plan, inventory, requirements=requirements()
    ).as_dict()[".ai-project/decisions.md"]

    assert "## Capability gap recommendations" in decisions
    assert "browser.validation: Validate user-visible browser behavior" in decisions
    assert decisions.index("playwright") < decisions.index("chrome-devtools")
    assert "read-project, execute-command" in decisions
    assert "only for interactive browser control" in decisions


def test_zero_gap_plan_renders_no_recommendation_section() -> None:
    blueprint, plan, inventory = inputs()
    plan = plan.model_copy(
        update={
            "resolutions": tuple(
                item for item in plan.resolutions if item.status is not ResolutionStatus.GAP
            )
        }
    )

    decisions = render_project_configuration(
        blueprint, plan, inventory, requirements=requirements()
    ).as_dict()[".ai-project/decisions.md"]

    assert "Capability gap recommendations" not in decisions
