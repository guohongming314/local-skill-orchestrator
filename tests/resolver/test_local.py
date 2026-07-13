from __future__ import annotations

from pathlib import Path

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


def repository(*, monorepo: bool, size: str) -> RepositorySnapshot:
    return RepositorySnapshot(
        root=Path("demo"),
        is_empty=False,
        facts=(
            RepositoryFact(
                key="is_monorepo",
                value=str(monorepo).lower(),
                confidence=FactConfidence.CONFIRMED,
            ),
            RepositoryFact(
                key="repository_size",
                value=size,
                confidence=FactConfidence.CONFIRMED,
            ),
        ),
        source_digest="repository-digest",
    )


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
    assert "large monorepos" in plan.resolutions[0].reason


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
        repository(monorepo=True, size="large"),
    )

    selected = [item for item in plan.resolutions if item.status is ResolutionStatus.SELECTED]
    assert [item.capability_id for item in selected] == ["product.codegraph"]
    assert "fit=" in selected[0].reason
    assert "trust=" in selected[0].reason
    assert "risk=" in selected[0].reason
    assert "verification=" in selected[0].reason


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
