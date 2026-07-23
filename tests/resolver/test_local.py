from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from vibe.inventory.adapters.base import (
    AdapterProvenance,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.inventory.service import InventoryResult
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot
from vibe.models.resolution import ResolutionStatus
from vibe.models.risk import RiskLevel
from vibe.practices.models import RequirementStrength
from vibe.remote.models import (
    CapabilityKind as RemoteCapabilityKind,
)
from vibe.remote.models import (
    PermissionLevel,
    Provenance,
    PublisherVerification,
    RemoteCandidate,
    SourceTier,
)
from vibe.remote.scoring import CandidateEvidence
from vibe.resolver.local import resolve_local_capabilities
from vibe.resolver.policy import ResolverPolicy
from vibe.resolver.requirements import AbstractCapabilityRequirement


def requirement(capability: str) -> AbstractCapabilityRequirement:
    return AbstractCapabilityRequirement(
        capability=capability,
        strength=RequirementStrength.RECOMMENDED,
        originating_packs=("fixture",),
        originating_requirements=(f"fixture-{capability}",),
        reasons=("Fixture requirement",),
        verification=("Verify fixture",),
    )


def candidate(
    capability_id: str,
    *,
    provides: tuple[str, ...],
    kind: CapabilityKind = CapabilityKind.CLI_TOOL,
    permissions: frozenset[Permission] = frozenset(),
    verified: bool = True,
    details: tuple[str, ...] = (),
) -> AdapterScanResult:
    manifest = CapabilityManifest(
        capability_id=capability_id,
        name=capability_id,
        kind=kind,
        scope=CapabilityScope.USER,
        source=f"fixture:{capability_id}",
        provides=provides,
        permissions=permissions,
        content_digest=f"digest-{capability_id}",
        verified=verified,
    )
    return AdapterScanResult(
        manifest=manifest,
        provenance=AdapterProvenance(adapter_id="fixture", locator=capability_id),
        verification=AdapterVerification(verified=verified, details=details),
    )


def inventory(*items: AdapterScanResult) -> InventoryResult:
    return InventoryResult(
        capabilities=items,
        diagnostics=(),
        inventory_digest="inventory-digest",
    )


def blueprint(*, lifecycle: LifecycleStage = LifecycleStage.ACTIVE_DEVELOPMENT) -> Blueprint:
    return Blueprint(
        project_name="demo",
        goal="Build safely",
        lifecycle_stage=lifecycle,
        risk_level=RiskLevel.MEDIUM,
        repository_digest="repository-digest",
    )


def repository(
    *,
    monorepo: bool,
    size: str,
    extra_facts: dict[str, str | list[str] | None] | None = None,
) -> RepositorySnapshot:
    facts: dict[str, str | list[str] | None] = {
        "is_monorepo": str(monorepo).lower(),
        "repository_size": size,
        **(extra_facts or {}),
    }
    return RepositorySnapshot(
        root=Path("demo"),
        is_empty=False,
        facts=tuple(
            RepositoryFact(
                key=key,
                value=value,
                confidence=FactConfidence.CONFIRMED,
            )
            for key, value in facts.items()
        ),
        source_digest="repository-digest",
    )


pytestmark = pytest.mark.validation


def test_small_projects_reject_unnecessary_codegraph() -> None:
    codegraph = candidate("product.codegraph", provides=("code-navigation",))

    plan = resolve_local_capabilities(
        (requirement("code-navigation"),),
        inventory(codegraph),
        blueprint(),
        repository(monorepo=False, size="small"),
    )

    assert [(item.status, item.capability_id) for item in plan.resolutions] == [
        (ResolutionStatus.REJECTED, "product.codegraph"),
        (ResolutionStatus.GAP, None),
    ]
    assert "context evidence" in plan.resolutions[0].reason


def test_large_monorepo_selects_available_codegraph() -> None:
    codegraph = candidate(
        "product.codegraph",
        provides=("code-navigation", "symbol-search"),
        permissions=frozenset({Permission.READ_PROJECT}),
    )

    plan = resolve_local_capabilities(
        (requirement("code-navigation"),),
        inventory(codegraph),
        blueprint(),
        repository(
            monorepo=True,
            size="large",
            extra_facts={
                "module_count": "25",
                "language_count": "2",
                "cross_module_changes": "frequent",
            },
        ),
    )

    selected = [item for item in plan.resolutions if item.status is ResolutionStatus.SELECTED]
    assert [item.capability_id for item in selected] == ["product.codegraph"]
    assert "fit=" in selected[0].reason
    assert "trust=" in selected[0].reason
    assert "risk=" in selected[0].reason
    assert "verification=" in selected[0].reason


def test_medium_complex_repository_selects_codegraph_with_context_evidence() -> None:
    codegraph = candidate("product.codegraph", provides=("code-navigation",))

    plan = resolve_local_capabilities(
        (requirement("code-navigation"),),
        inventory(codegraph),
        blueprint(),
        repository(
            monorepo=False,
            size="medium",
            extra_facts={
                "module_count": "30",
                "language_count": "3",
                "cross_module_changes": "frequent",
            },
        ),
    )

    assert plan.resolutions[0].status is ResolutionStatus.SELECTED
    assert "cross-module" in plan.resolutions[0].reason


def test_large_simple_repository_rejects_codegraph_with_context_evidence() -> None:
    codegraph = candidate("product.codegraph", provides=("code-navigation",))

    plan = resolve_local_capabilities(
        (requirement("code-navigation"),),
        inventory(codegraph),
        blueprint(),
        repository(
            monorepo=True,
            size="large",
            extra_facts={
                "module_count": "4",
                "language_count": "1",
                "cross_module_changes": "rare",
                "local_symbol_index": "true",
            },
        ),
    )

    assert plan.resolutions[0].status is ResolutionStatus.REJECTED
    assert "local symbol index" in plan.resolutions[0].reason


def test_short_lived_projects_defer_persistent_memory() -> None:
    memory = candidate("product.memory", provides=("cross-session-memory",))

    plan = resolve_local_capabilities(
        (requirement("cross-session-memory"),),
        inventory(memory),
        blueprint(lifecycle=LifecycleStage.EXPLORATION),
        repository(monorepo=False, size="small"),
    )

    assert len(plan.resolutions) == 1
    assert plan.resolutions[0].status is ResolutionStatus.DEFERRED
    assert "short-lived" in plan.resolutions[0].reason


def test_explicit_memory_denial_defers_installed_memory() -> None:
    memory = candidate("product.memory", provides=("cross-session-memory",))
    denied = blueprint().model_copy(update={"preferences": {"memory.persistence": "denied"}})

    plan = resolve_local_capabilities(
        (requirement("cross-session-memory"),),
        inventory(memory),
        denied,
        repository(monorepo=False, size="small"),
    )

    assert plan.resolutions[0].status is ResolutionStatus.DEFERRED
    assert "denied" in plan.resolutions[0].reason


def test_explicit_memory_preference_selects_memory_for_long_lived_project() -> None:
    memory = candidate("product.memory", provides=("cross-session-memory",))
    allowed = blueprint(lifecycle=LifecycleStage.MAINTENANCE).model_copy(
        update={"preferences": {"memory.persistence": True}}
    )

    plan = resolve_local_capabilities(
        (requirement("cross-session-memory"),),
        inventory(memory),
        allowed,
        repository(monorepo=False, size="small"),
    )

    assert plan.resolutions[0].status is ResolutionStatus.SELECTED
    assert "durable decisions" in plan.resolutions[0].reason


def test_unknown_memory_preference_does_not_infer_persistence_permission() -> None:
    memory = candidate("product.memory", provides=("cross-session-memory",))

    plan = resolve_local_capabilities(
        (requirement("cross-session-memory"),),
        inventory(memory),
        blueprint(lifecycle=LifecycleStage.PRODUCTION),
        repository(monorepo=False, size="small"),
    )

    assert plan.resolutions[0].status is ResolutionStatus.DEFERRED
    assert "explicit" in plan.resolutions[0].reason


def test_browser_runner_stays_preferred_without_interactive_preference() -> None:
    runner = candidate("cli.playwright", provides=("browser.validation",))
    interactive = candidate(
        "mcp.chrome-devtools",
        provides=("browser.validation",),
        kind=CapabilityKind.MCP,
    )

    plan = resolve_local_capabilities(
        (requirement("browser.validation"),),
        inventory(interactive, runner),
        blueprint(),
        repository(monorepo=False, size="small"),
    )

    assert plan.resolutions[0].capability_id == "cli.playwright"


def test_interactive_browser_preference_can_promote_mcp_candidate() -> None:
    runner = candidate("cli.playwright", provides=("browser.validation",))
    interactive = candidate(
        "mcp.chrome-devtools",
        provides=("browser.validation",),
        kind=CapabilityKind.MCP,
    )
    interactive_blueprint = blueprint().model_copy(
        update={"preferences": {"browser.interactive-debugging": True}}
    )

    plan = resolve_local_capabilities(
        (requirement("browser.validation"),),
        inventory(interactive, runner),
        interactive_blueprint,
        repository(monorepo=False, size="small"),
    )

    assert plan.resolutions[0].capability_id == "mcp.chrome-devtools"
    assert "interactive browser" in plan.resolutions[0].reason


def test_unknown_browser_preference_keeps_installed_mcp_as_provider() -> None:
    interactive = candidate(
        "mcp.chrome-devtools",
        provides=("browser.validation",),
        kind=CapabilityKind.MCP,
    )

    plan = resolve_local_capabilities(
        (requirement("browser.validation"),),
        inventory(interactive),
        blueprint(),
        repository(monorepo=False, size="small"),
    )

    assert plan.resolutions[0].status is ResolutionStatus.SELECTED
    assert "preference unknown" in plan.resolutions[0].reason


def test_lower_permission_cli_replaces_higher_permission_mcp() -> None:
    cli = candidate(
        "cli.search",
        provides=("semantic-search",),
        permissions=frozenset({Permission.READ_PROJECT, Permission.EXECUTE_COMMAND}),
    )
    mcp = candidate(
        "mcp.search",
        provides=("semantic-search",),
        kind=CapabilityKind.MCP,
        permissions=frozenset(
            {Permission.READ_PROJECT, Permission.EXECUTE_COMMAND, Permission.NETWORK}
        ),
    )
    policy = ResolverPolicy(
        allowed_permissions=frozenset(Permission),
    )

    plan = resolve_local_capabilities(
        (requirement("semantic-search"),),
        inventory(mcp, cli),
        blueprint(),
        repository(monorepo=False, size="medium"),
        policy=policy,
    )

    assert [(item.status, item.capability_id) for item in plan.resolutions] == [
        (ResolutionStatus.SELECTED, "cli.search"),
        (ResolutionStatus.REJECTED, "mcp.search"),
    ]
    assert "lower-ranked than cli.search" in plan.resolutions[1].reason


def test_permission_and_compatibility_hard_filters_are_explained() -> None:
    network = candidate(
        "cli.network",
        provides=("testing",),
        permissions=frozenset({Permission.NETWORK}),
    )
    incompatible = candidate(
        "plugin.other-host",
        provides=("testing",),
        kind=CapabilityKind.PLUGIN,
        details=("compatibility:other-host>=1",),
    )

    plan = resolve_local_capabilities(
        (requirement("testing"),),
        inventory(incompatible, network),
        blueprint(),
        repository(monorepo=False, size="small"),
    )

    reasons = {item.capability_id: item.reason for item in plan.resolutions}
    assert "permission filter" in reasons["cli.network"]
    assert "compatibility filter" in reasons["plugin.other-host"]
    assert plan.resolutions[-1].status is ResolutionStatus.GAP


def test_identical_inputs_produce_stable_reasons_and_order_and_empty_is_valid() -> None:
    items = inventory(
        candidate("cli.zeta", provides=("testing",)),
        candidate("cli.alpha", provides=("testing",)),
    )
    args = (
        (requirement("testing"),),
        items,
        blueprint(),
        repository(monorepo=False, size="small"),
    )

    assert resolve_local_capabilities(*args) == resolve_local_capabilities(*args)
    assert resolve_local_capabilities((), items, blueprint(), args[3]).resolutions == ()


def test_browser_validation_gap_yields_ranked_recommendations() -> None:
    plan = resolve_local_capabilities(
        (requirement("browser.validation"),),
        inventory(),
        blueprint(),
        repository(monorepo=False, size="small"),
    )

    gap = plan.resolutions[0]
    assert gap.status is ResolutionStatus.GAP
    assert gap.recommendation is not None
    assert gap.recommendation.why == "Fixture requirement"
    assert [candidate.provider for candidate in gap.recommendation.candidates] == [
        "playwright",
        "chrome-devtools",
    ]
    assert [candidate.kind for candidate in gap.recommendation.candidates] == [
        CapabilityKind.CLI_TOOL,
        CapabilityKind.MCP,
    ]
    assert gap.recommendation.candidates[0].permissions == (
        Permission.READ_PROJECT,
        Permission.EXECUTE_COMMAND,
    )
    assert gap.recommendation.candidates[0].strength is RequirementStrength.RECOMMENDED
    assert "deterministic" in gap.recommendation.candidates[0].why
    assert gap.recommendation.candidates[1].permissions == (
        Permission.READ_PROJECT,
        Permission.EXECUTE_COMMAND,
        Permission.NETWORK,
    )
    assert gap.recommendation.candidates[1].strength is RequirementStrength.OPTIONAL
    assert "only for interactive browser control" in gap.recommendation.candidates[1].why


def remote_candidate(
    name: str,
    *,
    kind: RemoteCapabilityKind,
    permission_level: PermissionLevel,
    permissions: tuple[str, ...],
    provides: tuple[str, ...] = ("browser.validation",),
) -> RemoteCandidate:
    digest = "sha256:" + hashlib.sha256(name.encode()).hexdigest()
    return RemoteCandidate(
        candidate_ref=f"registry:{name}@1.0.0",
        name=name,
        kind=kind,
        provides=provides,
        version="1.0.0",
        digest=digest,
        publisher=f"{name} publisher",
        permissions_as_declared=permissions,
        source_tier=SourceTier.OFFICIAL,
        provenance=Provenance(
            source="fixture-registry",
            publisher=f"{name} publisher",
            digest=digest,
            source_verified=True,
            publisher_verified=True,
            publisher_verification=PublisherVerification.ALLOWLIST,
            digest_verified=True,
            permission_level=permission_level,
            reason="fixture provenance",
        ),
    )


def test_browser_validation_gap_with_discovery_lists_scored_remote_cli_before_mcp() -> None:
    playwright = remote_candidate(
        "playwright",
        kind=RemoteCapabilityKind.CLI_TOOL,
        permission_level=PermissionLevel.L2,
        permissions=("read-project", "execute-command"),
    )
    browser_mcp = remote_candidate(
        "chrome-devtools",
        kind=RemoteCapabilityKind.MCP_SERVER,
        permission_level=PermissionLevel.L3,
        permissions=("read-project", "execute-command", "network-write"),
    )

    plan = resolve_local_capabilities(
        (requirement("browser.validation"),),
        inventory(),
        blueprint().model_copy(update={"risk_level": RiskLevel.HIGH}),
        repository(monorepo=False, size="small"),
        remote_candidates=(browser_mcp, playwright),
        remote_evidence={
            playwright.candidate_ref: CandidateEvidence(
                platforms=("codex",), maintenance=80, scan_flags=()
            ),
            browser_mcp.candidate_ref: CandidateEvidence(
                platforms=("codex",), maintenance=80, scan_flags=("network-write",)
            ),
        },
    )

    gap = plan.resolutions[0]
    assert gap.recommendation is not None
    candidates = gap.recommendation.candidates
    assert [candidate.provider for candidate in candidates] == [
        "playwright",
        "chrome-devtools",
    ]
    assert [candidate.permission_level for candidate in candidates] == ["L2", "L3"]
    assert candidates[0].approval_required == "show details and approve"
    assert candidates[1].approval_required == "approve individually"
    assert candidates[0].fit_score is not None
    assert candidates[0].trust_score is not None
    assert candidates[0].risk_score is not None
    assert candidates[1].risk_flags == ("network-write",)


def test_remote_discovery_disabled_preserves_existing_gap_payload() -> None:
    args = (
        (requirement("browser.validation"),),
        inventory(),
        blueprint(),
        repository(monorepo=False, size="small"),
    )

    assert resolve_local_capabilities(*args).model_dump(mode="json") == (
        resolve_local_capabilities(*args, remote_candidates=()).model_dump(mode="json")
    )


def test_unmet_e18_pack_requirements_resolve_to_gaps() -> None:
    from vibe.practices.evaluator import evaluate_practice_packs
    from vibe.practices.loader import load_practice_packs

    packs = load_practice_packs(Path(__file__).parents[2] / "practice-packs")
    production = blueprint(lifecycle=LifecycleStage.PRODUCTION)
    large_repo = repository(monorepo=True, size="large").model_copy(update={"is_empty": True})
    requirements = evaluate_practice_packs(packs, production, large_repo)

    plan = resolve_local_capabilities(
        requirements,
        inventory(),
        production,
        large_repo,
    )

    statuses = {
        item.requirement: item.status
        for item in plan.resolutions
        if item.requirement
        in {
            "git.recovery",
            "code.relationship-analysis",
            "project.continuity-memory",
            "release.rollback",
        }
    }
    assert statuses == {
        "git.recovery": ResolutionStatus.GAP,
        "code.relationship-analysis": ResolutionStatus.GAP,
        "project.continuity-memory": ResolutionStatus.GAP,
        "release.rollback": ResolutionStatus.GAP,
    }


@pytest.mark.parametrize(
    ("capability", "provider", "permissions"),
    [
        ("code.relationship-analysis", "codegraph", (Permission.READ_PROJECT,)),
        (
            "project.continuity-memory",
            "claude-mem",
            (Permission.READ_PROJECT, Permission.WRITE_PROJECT),
        ),
        (
            "git.recovery",
            "git",
            (Permission.READ_PROJECT, Permission.WRITE_PROJECT, Permission.EXECUTE_COMMAND),
        ),
        (
            "release.rollback",
            "deployment-rollback",
            (Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        ),
        (
            "ai.evaluation",
            "promptfoo",
            (Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        ),
        (
            "security.threat-model",
            "threat-modeling",
            (Permission.READ_PROJECT,),
        ),
        (
            "database.migration-testing",
            "alembic",
            (Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        ),
        (
            "api.contract-testing",
            "schemathesis",
            (Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        ),
        (
            "security.secret-scan",
            "gitleaks",
            (Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        ),
        (
            "accessibility.review",
            "axe-core",
            (Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        ),
        (
            "repository.exploration",
            "project-native-exploration",
            (Permission.READ_PROJECT,),
        ),
        (
            "quality.gates",
            "project-native-quality",
            (Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        ),
        (
            "development.design",
            "workflow-design",
            (Permission.READ_PROJECT,),
        ),
        (
            "code.optimization",
            "project-native-analysis",
            (Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        ),
    ],
)
def test_seeded_gap_domains_return_ranked_recommendations(
    capability: str,
    provider: str,
    permissions: tuple[Permission, ...],
) -> None:
    plan = resolve_local_capabilities(
        (requirement(capability),),
        inventory(),
        blueprint(),
        repository(monorepo=True, size="large"),
    )

    gap = plan.resolutions[0]
    assert gap.status is ResolutionStatus.GAP
    assert gap.recommendation is not None
    assert gap.recommendation.candidates[0].provider == provider
    assert gap.recommendation.candidates[0].permissions == permissions
    expected_strength = (
        RequirementStrength.REQUIRED
        if capability in {"repository.exploration", "quality.gates"}
        else RequirementStrength.RECOMMENDED
    )
    assert gap.recommendation.candidates[0].strength is expected_strength
    assert gap.recommendation.candidates[0].why


def test_unknown_gap_domain_explicitly_has_no_recommendation() -> None:
    plan = resolve_local_capabilities(
        (requirement("unknown.future-domain"),),
        inventory(),
        blueprint(),
        repository(monorepo=False, size="small"),
    )

    gap = plan.resolutions[0]
    assert gap.status is ResolutionStatus.GAP
    assert gap.recommendation is None


@pytest.mark.parametrize(
    ("capability", "kind", "strength", "explanation"),
    [
        (
            "repository.exploration",
            CapabilityKind.SKILL,
            RequirementStrength.REQUIRED,
            "repository-native search",
        ),
        (
            "quality.gates",
            CapabilityKind.CLI_TOOL,
            RequirementStrength.REQUIRED,
            "existing formatter",
        ),
        (
            "development.design",
            CapabilityKind.SKILL,
            RequirementStrength.RECOMMENDED,
            "comparing approaches",
        ),
        (
            "code.optimization",
            CapabilityKind.SKILL,
            RequirementStrength.RECOMMENDED,
            "repository measurements",
        ),
    ],
)
def test_development_loop_gap_recommendations_are_actionable(
    capability: str,
    kind: CapabilityKind,
    strength: RequirementStrength,
    explanation: str,
) -> None:
    plan = resolve_local_capabilities(
        (requirement(capability),),
        inventory(),
        blueprint(),
        repository(monorepo=False, size="small"),
    )

    recommendation = plan.resolutions[0].recommendation
    assert recommendation is not None
    candidate = recommendation.candidates[0]
    assert candidate.kind is kind
    assert candidate.strength is strength
    assert explanation in candidate.why


def test_gap_recommendations_ignore_remote_candidates_for_other_domains() -> None:
    browser_remote = remote_candidate(
        "browser-only",
        kind=RemoteCapabilityKind.CLI_TOOL,
        permission_level=PermissionLevel.L2,
        permissions=("read-project", "execute-command"),
    )

    plan = resolve_local_capabilities(
        (requirement("git.recovery"),),
        inventory(),
        blueprint(),
        repository(monorepo=False, size="small"),
        remote_candidates=(browser_remote,),
    )

    gap = plan.resolutions[0]
    assert gap.recommendation is not None
    assert [item.provider for item in gap.recommendation.candidates] == ["git"]


def test_non_browser_gap_ranks_matching_remote_candidate_with_local_default() -> None:
    remote = remote_candidate(
        "relationship-inspector",
        kind=RemoteCapabilityKind.CLI_TOOL,
        permission_level=PermissionLevel.L1,
        permissions=("read-project",),
        provides=("code.relationship-analysis",),
    )

    plan = resolve_local_capabilities(
        (requirement("code.relationship-analysis"),),
        inventory(),
        blueprint(),
        repository(monorepo=True, size="large"),
        remote_candidates=(remote,),
        remote_evidence={
            remote.candidate_ref: CandidateEvidence(
                platforms=("codex",), maintenance=90, scan_flags=()
            )
        },
    )

    gap = plan.resolutions[0]
    assert gap.status is ResolutionStatus.GAP
    assert gap.recommendation is not None
    assert [item.provider for item in gap.recommendation.candidates] == [
        "codegraph",
        "relationship-inspector",
    ]
    candidate = gap.recommendation.candidates[1]
    assert candidate.permission_level == "L1"
    assert candidate.fit_score is not None
    assert candidate.trust_score is not None
    assert candidate.risk_score is not None
    assert "Remote candidate" in candidate.why
