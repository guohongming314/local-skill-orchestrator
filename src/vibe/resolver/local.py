from __future__ import annotations

import hashlib
from collections.abc import Mapping

from vibe.inventory.adapters.base import AdapterScanResult
from vibe.inventory.service import InventoryResult
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.capability import CapabilityKind, Permission
from vibe.models.repository import RepositorySnapshot
from vibe.models.resolution import (
    CapabilityRecommendation,
    CapabilityResolution,
    RecommendationCandidate,
    ResolutionPlan,
    ResolutionStatus,
)
from vibe.practices.models import RequirementStrength
from vibe.remote.models import (
    CapabilityKind as RemoteCapabilityKind,
)
from vibe.remote.models import (
    PermissionLevel,
    RemoteCandidate,
)
from vibe.remote.scoring import (
    CandidateEvidence,
    RankedCandidate,
    ScoringContext,
    rank_candidates,
)
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
    remote_candidates: tuple[RemoteCandidate, ...] = (),
    remote_evidence: Mapping[str, CandidateEvidence] | None = None,
    rejected_remote_candidates: frozenset[str] = frozenset(),
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
                requirement,
                matching,
                blueprint,
                repository,
                active_policy,
                remote_candidates,
                remote_evidence or {},
                rejected_remote_candidates,
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
    remote_candidates: tuple[RemoteCandidate, ...],
    remote_evidence: Mapping[str, CandidateEvidence],
    rejected_remote_candidates: frozenset[str],
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
        recommendation=_gap_recommendation(
            requirement,
            blueprint,
            remote_candidates,
            remote_evidence,
            rejected_remote_candidates,
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


def _gap_recommendation(
    requirement: AbstractCapabilityRequirement,
    blueprint: Blueprint,
    remote_candidates: tuple[RemoteCandidate, ...],
    remote_evidence: Mapping[str, CandidateEvidence],
    rejected_remote_candidates: frozenset[str],
) -> CapabilityRecommendation | None:
    if requirement.capability != "browser.validation":
        return None
    local_candidates: tuple[RecommendationCandidate, ...] = (
        RecommendationCandidate(
            kind=CapabilityKind.CLI_TOOL,
            provider="playwright",
            permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
            why=(
                "Prefer a low-permission local deterministic browser test tool "
                "for repeatable validation."
            ),
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
            why="Use this browser MCP only for interactive browser control.",
            strength=RequirementStrength.OPTIONAL,
        ),
    )
    candidates: tuple[RecommendationCandidate, ...]
    if not remote_candidates:
        candidates = local_candidates
    else:
        rejected_names = {
            candidate.name
            for candidate in remote_candidates
            if candidate.candidate_ref in rejected_remote_candidates
        }
        local_candidates = tuple(
            item for item in local_candidates if item.provider not in rejected_names
        )
        eligible = tuple(
            candidate
            for candidate in remote_candidates
            if candidate.candidate_ref not in rejected_remote_candidates
        )
        ranked = tuple(
            sorted(
                rank_candidates(
                    eligible,
                    ScoringContext(
                        requirement=requirement.capability,
                        target_platforms=blueprint.target_platforms,
                        project_risk_level=blueprint.risk_level,
                    ),
                    evidence=remote_evidence,
                ),
                key=_remote_recommendation_order,
            )
        )
        remote_by_name = {item.candidate.name: item for item in ranked}
        merged = [
            _remote_recommendation(
                remote_by_name.pop(item.provider), remote_evidence
            )
            if item.provider in remote_by_name
            else item
            for item in local_candidates
        ]
        merged.extend(
            _remote_recommendation(item, remote_evidence)
            for item in ranked
            if item.candidate.name in remote_by_name
        )
        candidates = tuple(merged)
    if not candidates:
        return None
    return CapabilityRecommendation(
        why="; ".join(requirement.reasons),
        candidates=candidates,
    )


def _remote_recommendation(
    ranked: RankedCandidate, evidence: Mapping[str, CandidateEvidence]
) -> RecommendationCandidate:
    candidate = ranked.candidate
    provenance = candidate.provenance
    permission_level = (
        provenance.permission_level if provenance is not None else PermissionLevel.L4
    )
    return RecommendationCandidate(
        kind=_remote_kind(candidate.kind),
        provider=candidate.name,
        permissions=_remote_permissions(candidate.permissions_as_declared),
        why=(
            f"Remote candidate; {ranked.fit.explanation}; "
            f"{ranked.trust.explanation}; {ranked.risk.explanation}"
        ),
        strength=(
            RequirementStrength.RECOMMENDED
            if candidate.kind is RemoteCapabilityKind.CLI_TOOL
            else RequirementStrength.OPTIONAL
        ),
        candidate_ref=candidate.candidate_ref,
        permission_level=permission_level.value,
        approval_required=_approval_required(permission_level),
        fit_score=ranked.fit.score,
        trust_score=ranked.trust.score,
        risk_score=ranked.risk.score,
        score_explanations=(
            ranked.fit.explanation,
            ranked.trust.explanation,
            ranked.risk.explanation,
        ),
        risk_flags=evidence.get(candidate.candidate_ref, CandidateEvidence()).scan_flags,
    )


def _remote_kind(kind: RemoteCapabilityKind) -> CapabilityKind:
    return {
        RemoteCapabilityKind.MCP_SERVER: CapabilityKind.MCP,
        RemoteCapabilityKind.AGENT_SKILL: CapabilityKind.SKILL,
        RemoteCapabilityKind.PLUGIN: CapabilityKind.PLUGIN,
        RemoteCapabilityKind.CLI_TOOL: CapabilityKind.CLI_TOOL,
    }[kind]


def _remote_permissions(values: tuple[str, ...]) -> tuple[Permission, ...]:
    aliases = {
        "read-project": Permission.READ_PROJECT,
        "filesystem-read": Permission.READ_PROJECT,
        "write-project": Permission.WRITE_PROJECT,
        "filesystem-write": Permission.WRITE_PROJECT,
        "execute-command": Permission.EXECUTE_COMMAND,
        "command-execution": Permission.EXECUTE_COMMAND,
        "network": Permission.NETWORK,
        "network-read": Permission.NETWORK,
        "network-write": Permission.NETWORK,
    }
    return tuple(
        dict.fromkeys(
            aliases[value.lower()] for value in values if value.lower() in aliases
        )
    )


def _approval_required(level: PermissionLevel) -> str:
    return {
        PermissionLevel.L0: "automatic use",
        PermissionLevel.L1: "approve once",
        PermissionLevel.L2: "show details and approve",
        PermissionLevel.L3: "approve individually",
        PermissionLevel.L4: "blocked",
    }[level]


def _remote_recommendation_order(item: RankedCandidate) -> tuple[int, int, str]:
    provenance = item.candidate.provenance
    level = provenance.permission_level if provenance is not None else PermissionLevel.L4
    permission_order = {
        PermissionLevel.L0: 0,
        PermissionLevel.L1: 1,
        PermissionLevel.L2: 2,
        PermissionLevel.L3: 3,
        PermissionLevel.L4: 4,
    }[level]
    kind_order = {
        RemoteCapabilityKind.CLI_TOOL: 0,
        RemoteCapabilityKind.AGENT_SKILL: 1,
        RemoteCapabilityKind.PLUGIN: 1,
        RemoteCapabilityKind.MCP_SERVER: 2,
    }[item.candidate.kind]
    return kind_order, permission_order, item.candidate.candidate_ref
