from __future__ import annotations

from pathlib import Path

import yaml

from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.adapters.base import (
    AdapterProvenance,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.inventory.service import InventoryResult
from vibe.materialize.templates import render_project_configuration, validate_rendered_yaml
from vibe.models.blueprint import Blueprint, LifecycleStage, ProjectConstraint
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)
from vibe.models.resolution import (
    CapabilityRecommendation,
    CapabilityResolution,
    RecommendationCandidate,
    ResolutionPlan,
    ResolutionStatus,
)
from vibe.models.risk import RiskLevel
from vibe.practices.models import RequirementStrength

FIXTURE = Path(__file__).parents[1] / "fixtures" / "generated" / "project.snapshot"


def capability(
    capability_id: str,
    *,
    provides: tuple[str, ...],
    digest: str,
    kind: CapabilityKind = CapabilityKind.CLI_TOOL,
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
    )
    return AdapterScanResult(
        manifest=manifest,
        provenance=AdapterProvenance("fixture", capability_id),
        verification=AdapterVerification(True, ("fixture verified",)),
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
                requirement="release-automation",
                status=ResolutionStatus.GAP,
                reason="no local provider",
            ),
        ),
    )
    return blueprint, plan, inventory


def test_renders_complete_project_configuration_and_all_yaml_validates() -> None:
    rendered = render_project_configuration(*inputs())
    files = rendered.as_dict()

    assert set(files) == {
        ".ai-project/blueprint.yaml",
        ".ai-project/capabilities.yaml",
        ".ai-project/capabilities.lock",
        ".ai-project/policy.yaml",
        ".ai-project/decisions.md",
        ".ai-project/quality-gates.md",
        ".ai-project/workflows.yaml",
        ".ai-project/task-policies.yaml",
        ".ai-project/capability-usage.yaml",
        ".agents/skills/project-development/SKILL.md",
        ".agents/skills/project-development/references/capability-routing.md",
        ".agents/skills/project-development/references/quality-gates.md",
    }
    validate_rendered_yaml(rendered)
    Blueprint.model_validate(yaml.safe_load(files[".ai-project/blueprint.yaml"]))


def test_lockfile_pins_selected_provider_identity_and_content_digest() -> None:
    files = render_project_configuration(*inputs()).as_dict()

    lock = yaml.safe_load(files[".ai-project/capabilities.lock"])

    assert lock["schema_version"] == "1"
    assert lock["inventory_digest"] == "inventory-digest"
    assert lock["providers"] == [
        {
            "provider_id": "cli.pytest",
            "kind": "cli-tool",
            "scope": "user",
            "source": "local:cli.pytest",
            "version": "1.2.3",
            "content_digest": "pytest-content-digest",
        }
    ]
    assert "mcp.search" not in files[".ai-project/capabilities.lock"]


def test_rendered_snapshot_is_byte_stable() -> None:
    first = render_project_configuration(*inputs()).snapshot_bytes()
    second = render_project_configuration(*inputs()).snapshot_bytes()

    assert first == second
    assert first == FIXTURE.read_bytes()


def test_generated_project_skill_passes_local_structural_validation(tmp_path: Path) -> None:
    rendered = render_project_configuration(*inputs())
    for relative_path, content in rendered.as_dict().items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    skill_root = tmp_path / ".agents" / "skills"
    adapter = AgentSkillAdapter(
        roots=(SkillRoot(skill_root, CapabilityScope.PROJECT),)
    )
    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.capability_id == "skill.project-development"
    assert result.manifest.version == "1.0.0"
    assert result.verification.verified
    assert result.verification.details == (
        "dependency:references/capability-routing.md",
        "dependency:references/quality-gates.md",
    )


def test_template_sources_are_versioned_and_do_not_contain_project_values() -> None:
    template_root = Path(__file__).parents[2] / "templates" / "project-development"

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

    decisions = render_project_configuration(blueprint, plan, inventory).as_dict()[
        ".ai-project/decisions.md"
    ]

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

    decisions = render_project_configuration(blueprint, plan, inventory).as_dict()[
        ".ai-project/decisions.md"
    ]

    assert "Capability gap recommendations" not in decisions
