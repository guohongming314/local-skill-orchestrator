from __future__ import annotations

from dataclasses import dataclass

from vibe.inventory.adapters.base import AdapterScanResult
from vibe.models.blueprint import Blueprint
from vibe.models.capability import Permission
from vibe.policy.org import OrgPolicy
from vibe.remote.models import PermissionLevel, RemoteCandidate

_DEFAULT_PERMISSIONS = frozenset(
    {
        Permission.READ_PROJECT,
        Permission.WRITE_PROJECT,
        Permission.EXECUTE_COMMAND,
    }
)


@dataclass(frozen=True)
class ResolverPolicy:
    """Hard policy boundaries applied before local candidate scoring."""

    allowed_permissions: frozenset[Permission] = _DEFAULT_PERMISSIONS
    org_policy: OrgPolicy | None = None
    org_policy_path: str | None = None


def hard_filter_reason(
    candidate: AdapterScanResult,
    blueprint: Blueprint,
    policy: ResolverPolicy,
) -> str | None:
    org_policy = policy.org_policy
    if org_policy is not None:
        capability_id = candidate.manifest.capability_id
        if capability_id in org_policy.blocked_capability_ids:
            return f"blocked by org policy {policy.org_policy_path}"
        if (
            org_policy.approved_capability_ids
            and capability_id not in org_policy.approved_capability_ids
        ):
            return f"not approved by org policy {policy.org_policy_path}"
        org_denied = sorted(
            permission.value
            for permission in candidate.manifest.permissions - org_policy.allowed_permissions
        )
        if org_denied:
            return (
                f"exceeds permission ceiling in org policy {policy.org_policy_path}: "
                + ", ".join(org_denied)
            )
    denied = sorted(
        permission.value
        for permission in candidate.manifest.permissions - policy.allowed_permissions
    )
    if denied:
        return f"permission filter rejected disallowed permissions: {', '.join(denied)}"
    compatibility = _declared_compatibility(candidate)
    if compatibility is not None and not any(
        compatibility.startswith(platform) for platform in blueprint.target_platforms
    ):
        return (
            f"compatibility filter rejected {compatibility!r}; target platforms are "
            f"{', '.join(sorted(blueprint.target_platforms))}"
        )
    return None


def _declared_compatibility(candidate: AdapterScanResult) -> str | None:
    prefix = "compatibility:"
    for detail in candidate.verification.details:
        if detail.startswith(prefix):
            return detail.removeprefix(prefix)
    return None


_PERMISSION_LEVEL_ORDER = {
    PermissionLevel.L0: 0,
    PermissionLevel.L1: 1,
    PermissionLevel.L2: 2,
    PermissionLevel.L3: 3,
    PermissionLevel.L4: 4,
}


def remote_org_filter_reason(
    candidate: RemoteCandidate, policy: ResolverPolicy
) -> str | None:
    """Apply organization hard filters before remote candidate scoring."""
    org_policy = policy.org_policy
    if org_policy is None:
        return None
    identifiers = {candidate.candidate_ref, candidate.name}
    if identifiers.intersection(org_policy.blocked_capability_ids):
        return f"blocked by org policy {policy.org_policy_path}"
    if (
        org_policy.approved_capability_ids
        and not identifiers.intersection(org_policy.approved_capability_ids)
    ):
        return f"not approved by org policy {policy.org_policy_path}"
    publisher = candidate.publisher
    if publisher in org_policy.blocked_publishers:
        return f"blocked by org policy {policy.org_policy_path}"
    if (
        publisher is not None
        and org_policy.approved_publishers
        and publisher not in org_policy.approved_publishers
    ):
        return f"not approved by org policy {policy.org_policy_path}"
    provenance = candidate.provenance
    level = provenance.permission_level if provenance is not None else PermissionLevel.L4
    if (
        _PERMISSION_LEVEL_ORDER[level]
        > _PERMISSION_LEVEL_ORDER[org_policy.max_permission_level]
    ):
        return f"exceeds permission ceiling in org policy {policy.org_policy_path}"
    return None
