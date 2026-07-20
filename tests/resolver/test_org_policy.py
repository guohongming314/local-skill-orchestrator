from __future__ import annotations

from pathlib import Path

import pytest

from vibe.inventory.adapters.base import (
    AdapterProvenance,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.inventory.service import InventoryResult
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.capability import CapabilityKind, CapabilityManifest, CapabilityScope
from vibe.models.repository import RepositorySnapshot
from vibe.models.resolution import ResolutionPlan, ResolutionStatus
from vibe.models.risk import RiskLevel
from vibe.practices.models import RequirementStrength
from vibe.resolver.local import resolve_local_capabilities
from vibe.resolver.requirements import AbstractCapabilityRequirement

pytestmark = pytest.mark.validation

def _candidate(capability_id: str, *, verified: bool = True) -> AdapterScanResult:
    return AdapterScanResult(
        manifest=CapabilityManifest(
            capability_id=capability_id,
            name=capability_id,
            kind=CapabilityKind.CLI_TOOL,
            scope=CapabilityScope.USER,
            source=f"fixture:{capability_id}",
            provides=("testing",),
            content_digest=f"digest-{capability_id}",
            verified=verified,
        ),
        provenance=AdapterProvenance(adapter_id="fixture", locator=capability_id),
        verification=AdapterVerification(verified=verified),
    )


def _resolve(root: Path) -> ResolutionPlan:
    preferred = _candidate("org.blocked")
    fallback = _candidate("org.allowed", verified=False)
    return resolve_local_capabilities(
        (
            AbstractCapabilityRequirement(
                capability="testing",
                strength=RequirementStrength.RECOMMENDED,
                originating_packs=("fixture",),
                originating_requirements=("fixture-testing",),
                reasons=("Fixture requirement",),
                verification=("Verify fixture",),
            ),
        ),
        InventoryResult(
            capabilities=(preferred, fallback),
            diagnostics=(),
            inventory_digest="inventory-digest",
        ),
        Blueprint(
            project_name="demo",
            goal="Build safely",
            lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
            risk_level=RiskLevel.MEDIUM,
            repository_digest="repository-digest",
            preferences={"testing": "org.blocked"},
        ),
        RepositorySnapshot(
            root=root,
            is_empty=False,
            facts=(),
            source_digest="repository-digest",
        ),
        org_policy_path=root / "org-policy.yaml",
    )


def test_org_blocked_capability_never_resolves_even_if_user_preferred(
    tmp_path: Path,
) -> None:
    policy_path = tmp_path / "org-policy.yaml"
    policy_path.write_text(
        "schema_version: '1'\nblocked_capability_ids:\n  - org.blocked\n",
        encoding="utf-8",
    )

    plan = _resolve(tmp_path)

    resolutions = {item.capability_id: item for item in plan.resolutions}
    assert resolutions["org.blocked"].status is ResolutionStatus.REJECTED
    assert resolutions["org.blocked"].reason == f"blocked by org policy {policy_path}"
    assert resolutions["org.allowed"].status is ResolutionStatus.SELECTED


def test_missing_org_policy_file_is_a_no_op(tmp_path: Path) -> None:
    plan = _resolve(tmp_path)

    selected = [item for item in plan.resolutions if item.status is ResolutionStatus.SELECTED]
    assert [item.capability_id for item in selected] == ["org.blocked"]


def test_org_policy_filters_unapproved_ids_and_permission_ceiling(tmp_path: Path) -> None:
    policy_path = tmp_path / "org-policy.yaml"
    policy_path.write_text(
        """schema_version: '1'
approved_capability_ids: [org.allowed]
allowed_permissions: [read-project]
""",
        encoding="utf-8",
    )
    policy_candidate = _candidate("org.allowed")
    disallowed = _candidate("org.other")
    from vibe.models.capability import Permission

    too_powerful_manifest = policy_candidate.manifest.model_copy(
        update={"permissions": frozenset({Permission.EXECUTE_COMMAND})}
    )
    too_powerful = AdapterScanResult(
        manifest=too_powerful_manifest,
        provenance=policy_candidate.provenance,
        verification=policy_candidate.verification,
    )
    from vibe.policy.org import load_org_policy
    from vibe.resolver.policy import ResolverPolicy, hard_filter_reason

    org_policy, loaded_path = load_org_policy(tmp_path, policy_path)
    policy = ResolverPolicy(org_policy=org_policy, org_policy_path=str(loaded_path))

    assert hard_filter_reason(disallowed, Blueprint(
        project_name="demo", goal="Build safely",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM, repository_digest="repository-digest",
    ), policy) == f"not approved by org policy {policy_path}"
    assert hard_filter_reason(too_powerful, Blueprint(
        project_name="demo", goal="Build safely",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM, repository_digest="repository-digest",
    ), policy) == f"exceeds permission ceiling in org policy {policy_path}: execute-command"


def test_org_policy_path_precedence_supports_env_repo_and_home(tmp_path: Path) -> None:
    from vibe.policy.org import ORG_POLICY_ENV, org_policy_path

    root = tmp_path / "repo"
    home = tmp_path / "home"
    root.mkdir()
    env_path = tmp_path / "environment-policy.yaml"
    assert org_policy_path(root, environ={ORG_POLICY_ENV: str(env_path)}, home=home) == env_path

    (root / "org-policy.yaml").write_text("schema_version: '1'\n", encoding="utf-8")
    assert org_policy_path(root, environ={}, home=home) == root / "org-policy.yaml"

    (root / "org-policy.yaml").unlink()
    assert org_policy_path(root, environ={}, home=home) == home / ".config/vibe/org-policy.yaml"


def test_org_remote_approvals_filter_publishers_without_bypassing_l_consent(
    tmp_path: Path,
) -> None:
    import hashlib

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

    def remote(name: str, publisher: str, level: PermissionLevel) -> RemoteCandidate:
        digest = "sha256:" + hashlib.sha256(name.encode()).hexdigest()
        return RemoteCandidate(
            candidate_ref=f"registry:{name}@1",
            name=name,
            kind=RemoteCapabilityKind.CLI_TOOL,
            provides=("browser.validation",),
            digest=digest,
            publisher=publisher,
            permissions_as_declared=("read-project", "execute-command"),
            source_tier=SourceTier.OFFICIAL,
            provenance=Provenance(
                source="fixture",
                publisher=publisher,
                digest=digest,
                source_verified=True,
                publisher_verified=True,
                publisher_verification=PublisherVerification.ORG_SIGNATURE,
                digest_verified=True,
                permission_level=level,
                reason="fixture",
            ),
        )

    policy_path = tmp_path / "org-policy.yaml"
    policy_path.write_text(
        """schema_version: '1'
approved_publishers: [approved.example]
blocked_publishers: [blocked.example]
max_permission_level: L2
""",
        encoding="utf-8",
    )
    plan = resolve_local_capabilities(
        (
            AbstractCapabilityRequirement(
                capability="browser.validation",
                strength=RequirementStrength.RECOMMENDED,
                originating_packs=("fixture",),
                originating_requirements=("browser",),
                reasons=("Browser verification",),
                verification=("Run browser tests",),
            ),
        ),
        InventoryResult(capabilities=(), diagnostics=(), inventory_digest="inventory-digest"),
        Blueprint(
            project_name="demo",
            goal="Build safely",
            lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
            risk_level=RiskLevel.HIGH,
            repository_digest="repository-digest",
        ),
        RepositorySnapshot(
            root=tmp_path,
            is_empty=False,
            facts=(),
            source_digest="repository-digest",
        ),
        org_policy_path=policy_path,
        remote_candidates=(
            remote("approved", "approved.example", PermissionLevel.L2),
            remote("blocked", "blocked.example", PermissionLevel.L1),
            remote("too-powerful", "approved.example", PermissionLevel.L3),
        ),
    )

    gap = next(item for item in plan.resolutions if item.status is ResolutionStatus.GAP)
    assert gap.recommendation is not None
    remote_recommendations = [
        item for item in gap.recommendation.candidates if item.candidate_ref is not None
    ]
    assert [item.provider for item in remote_recommendations] == ["approved"]
    assert remote_recommendations[0].approval_required == "show details and approve"


def test_mandatory_org_practice_pack_adds_its_requirements(tmp_path: Path) -> None:
    policy_path = tmp_path / "org-policy.yaml"
    policy_path.write_text(
        "schema_version: '1'\nmandatory_practice_packs: [base-engineering]\n",
        encoding="utf-8",
    )

    plan = resolve_local_capabilities(
        (),
        InventoryResult(capabilities=(), diagnostics=(), inventory_digest="inventory-digest"),
        Blueprint(
            project_name="demo",
            goal="Build safely",
            lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
            risk_level=RiskLevel.MEDIUM,
            repository_digest="repository-digest",
        ),
        RepositorySnapshot(
            root=tmp_path,
            is_empty=False,
            facts=(),
            source_digest="repository-digest",
        ),
        org_policy_path=policy_path,
    )

    assert {item.requirement for item in plan.resolutions} == {
        "repository.exploration",
        "quality.gates",
        "git.recovery",
    }
    assert all("base-engineering" in item.reason for item in plan.resolutions)
