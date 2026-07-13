from __future__ import annotations

import hashlib

from vibe.inventory.adapters.base import AdapterScanResult
from vibe.inventory.service import InventoryResult
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.repository import RepositorySnapshot
from vibe.models.resolution import CapabilityResolution, ResolutionPlan, ResolutionStatus
from vibe.resolver.policy import ResolverPolicy, hard_filter_reason
from vibe.resolver.requirements import AbstractCapabilityRequirement
from vibe.resolver.scoring import CandidateScore, score_candidate


def resolve_local_capabilities(
    requirements: tuple[AbstractCapabilityRequirement, ...],
    inventory: InventoryResult,
    blueprint: Blueprint,
    repository: RepositorySnapshot,
    *,
    policy: ResolverPolicy | None = None,
) -> ResolutionPlan:
    """Resolve abstract requirements to the minimal deterministic local selection."""
    active_policy = policy or ResolverPolicy()
    resolutions: list[CapabilityResolution] = []
    for requirement in sorted(requirements, key=lambda item: item.capability):
        matching = sorted(
            (
                item
                for item in inventory.capabilities
                if requirement.capability in item.manifest.provides
            ),
            key=lambda item: item.manifest.capability_id,
        )
        resolutions.extend(
            _resolve_requirement(
                requirement, matching, blueprint, repository, active_policy
            )
        )
    return ResolutionPlan(
        blueprint_digest=_blueprint_digest(blueprint),
        inventory_digest=inventory.inventory_digest,
        resolutions=tuple(resolutions),
    )


def _resolve_requirement(
    requirement: AbstractCapabilityRequirement,
    candidates: list[AdapterScanResult],
    blueprint: Blueprint,
    repository: RepositorySnapshot,
    policy: ResolverPolicy,
) -> list[CapabilityResolution]:
    rejected: list[CapabilityResolution] = []
    eligible: list[tuple[AdapterScanResult, CandidateScore]] = []
    for candidate in candidates:
        contextual_reason = _contextual_filter(candidate, blueprint, repository)
        if contextual_reason is not None:
            status = (
                ResolutionStatus.DEFERRED
                if _is_persistent_memory(candidate)
                else ResolutionStatus.REJECTED
            )
            rejected.append(
                _resolution(requirement, status, candidate, contextual_reason)
            )
            continue
        policy_reason = hard_filter_reason(candidate, blueprint, policy)
        if policy_reason is not None:
            rejected.append(
                _resolution(requirement, ResolutionStatus.REJECTED, candidate, policy_reason)
            )
            continue
        eligible.append((candidate, score_candidate(candidate, requirement.capability)))

    if eligible:
        eligible.sort(key=_ranking_key)
        winner, winner_score = eligible[0]
        selected = _resolution(
            requirement,
            ResolutionStatus.SELECTED,
            winner,
            f"selected local provider; {winner_score.explanation()}",
        )
        lower_ranked = [
            _resolution(
                requirement,
                ResolutionStatus.REJECTED,
                candidate,
                (
                    f"lower-ranked than {winner.manifest.capability_id}; "
                    f"{score.explanation()} versus {winner_score.explanation()}"
                ),
            )
            for candidate, score in eligible[1:]
        ]
        return [selected, *sorted((*rejected, *lower_ranked), key=_resolution_key)]

    if rejected and all(item.status is ResolutionStatus.DEFERRED for item in rejected):
        return sorted(rejected, key=_resolution_key)
    gap = CapabilityResolution(
        requirement=requirement.capability,
        status=ResolutionStatus.GAP,
        reason=(
            "no policy-compliant local provider; required by packs "
            + ", ".join(requirement.originating_packs)
        ),
    )
    return [*sorted(rejected, key=_resolution_key), gap]


def _contextual_filter(
    candidate: AdapterScanResult,
    blueprint: Blueprint,
    repository: RepositorySnapshot,
) -> str | None:
    if _is_codegraph(candidate) and not _is_large_monorepo(repository):
        return "CodeGraph is reserved for large monorepos where graph navigation adds value"
    if _is_persistent_memory(candidate) and blueprint.lifecycle_stage is LifecycleStage.EXPLORATION:
        return "persistent memory deferred for a short-lived exploration project"
    return None


def _is_codegraph(candidate: AdapterScanResult) -> bool:
    return "codegraph" in candidate.manifest.capability_id.casefold()


def _is_persistent_memory(candidate: AdapterScanResult) -> bool:
    return "cross-session-memory" in candidate.manifest.provides


def _is_large_monorepo(repository: RepositorySnapshot) -> bool:
    facts = {item.key: item.value for item in repository.facts}
    monorepo = facts.get("is_monorepo") in (True, "true", "True", "yes")
    return monorepo and facts.get("repository_size") == "large"


def _ranking_key(
    item: tuple[AdapterScanResult, CandidateScore],
) -> tuple[int, int, str]:
    candidate, score = item
    return (-score.total, len(candidate.manifest.permissions), candidate.manifest.capability_id)


def _resolution(
    requirement: AbstractCapabilityRequirement,
    status: ResolutionStatus,
    candidate: AdapterScanResult,
    reason: str,
) -> CapabilityResolution:
    return CapabilityResolution(
        requirement=requirement.capability,
        status=status,
        capability_id=candidate.manifest.capability_id,
        reason=reason,
    )


def _resolution_key(item: CapabilityResolution) -> tuple[str, str]:
    return (item.capability_id or "", item.reason)


def _blueprint_digest(blueprint: Blueprint) -> str:
    payload = blueprint.model_dump_json(exclude_none=True)
    return hashlib.sha256(payload.encode()).hexdigest()
