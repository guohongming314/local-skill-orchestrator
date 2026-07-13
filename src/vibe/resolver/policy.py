from __future__ import annotations

from dataclasses import dataclass

from vibe.inventory.adapters.base import AdapterScanResult
from vibe.models.blueprint import Blueprint
from vibe.models.capability import Permission

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


def hard_filter_reason(
    candidate: AdapterScanResult,
    blueprint: Blueprint,
    policy: ResolverPolicy,
) -> str | None:
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
