from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

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
from vibe.policy.org import load_org_policy
from vibe.practices.loader import load_practice_pack
from vibe.practices.models import RequirementStrength
from vibe.practices.paths import bundled_practice_packs_root
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
    rank_multi_source_candidates,
)
from vibe.resolver.policy import (
    ResolverPolicy,
    hard_filter_reason,
    remote_org_filter_reason,
)
from vibe.resolver.requirements import AbstractCapabilityRequirement
from vibe.resolver.scoring import CandidateScore, score_candidate


def resolve_local_capabilities(
    requirements: tuple[AbstractCapabilityRequirement, ...],
    inventory: InventoryResult,
    blueprint: Blueprint,
    repository: RepositorySnapshot,
    *,
    policy: ResolverPolicy | None = None,
    org_policy_path: Path | None = None,
    remote_candidates: tuple[RemoteCandidate, ...] = (),
    remote_evidence: Mapping[str, CandidateEvidence] | None = None,
    rejected_remote_candidates: frozenset[str] = frozenset(),
) -> ResolutionPlan:
    """Resolve abstract requirements to the minimal deterministic local selection."""
    active_policy = policy or ResolverPolicy()
    if active_policy.org_policy is None:
        org_policy, loaded_path = load_org_policy(repository.root, org_policy_path)
        active_policy = ResolverPolicy(
            allowed_permissions=active_policy.allowed_permissions,
            org_policy=org_policy,
            org_policy_path=str(loaded_path),
        )
    effective_requirements = _with_mandatory_practice_packs(
        requirements, active_policy
    )
    resolutions: list[CapabilityResolution] = []
    for requirement in sorted(effective_requirements, key=lambda item: item.capability):
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


_STRENGTH_ORDER = {
    RequirementStrength.OPTIONAL: 0,
    RequirementStrength.RECOMMENDED: 1,
    RequirementStrength.REQUIRED: 2,
}


def _with_mandatory_practice_packs(
    requirements: tuple[AbstractCapabilityRequirement, ...],
    policy: ResolverPolicy,
) -> tuple[AbstractCapabilityRequirement, ...]:
    org_policy = policy.org_policy
    if org_policy is None or not org_policy.mandatory_practice_packs:
        return requirements
    by_capability = {item.capability: item for item in requirements}
    for pack_id in sorted(org_policy.mandatory_practice_packs):
        pack = load_practice_pack(
            bundled_practice_packs_root() / pack_id / "pack.yaml"
        )
        for item in pack.requirements:
            existing = by_capability.get(item.capability)
            if existing is None:
                by_capability[item.capability] = AbstractCapabilityRequirement(
                    capability=item.capability,
                    strength=item.strength,
                    originating_packs=(pack_id,),
                    originating_requirements=(item.requirement_id,),
                    reasons=(item.rationale,),
                    verification=item.verification,
                )
                continue
            strength = max(
                (existing.strength, item.strength), key=_STRENGTH_ORDER.__getitem__
            )
            by_capability[item.capability] = existing.model_copy(
                update={
                    "strength": strength,
                    "originating_packs": tuple(
                        sorted({*existing.originating_packs, pack_id})
                    ),
                    "originating_requirements": tuple(
                        sorted({*existing.originating_requirements, item.requirement_id})
                    ),
                    "reasons": tuple(dict.fromkeys((*existing.reasons, item.rationale))),
                    "verification": tuple(
                        dict.fromkeys((*existing.verification, *item.verification))
                    ),
                }
            )
    return tuple(by_capability.values())


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
            policy,
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


_LOCAL_GAP_RECOMMENDATIONS: dict[str, tuple[RecommendationCandidate, ...]] = {
    "browser.validation": (
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
    ),
    "code.relationship-analysis": (
        RecommendationCandidate(
            kind=CapabilityKind.CLI_TOOL,
            provider="codegraph",
            permissions=(Permission.READ_PROJECT,),
            why=(
                "Prefer read-only deterministic graph analysis for repeatable "
                "cross-package relationship tracing."
            ),
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "project.continuity-memory": (
        RecommendationCandidate(
            kind=CapabilityKind.MCP,
            provider="claude-mem",
            permissions=(Permission.READ_PROJECT, Permission.WRITE_PROJECT),
            why=(
                "Use persistent project memory only for durable cross-session context; "
                "keep stored context scoped to the project."
            ),
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "git.recovery": (
        RecommendationCandidate(
            kind=CapabilityKind.CLI_TOOL,
            provider="git",
            permissions=(
                Permission.READ_PROJECT,
                Permission.WRITE_PROJECT,
                Permission.EXECUTE_COMMAND,
            ),
            why=(
                "Prefer the deterministic local Git CLI for inspecting history and "
                "performing explicit restore or revert operations."
            ),
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "release.rollback": (
        RecommendationCandidate(
            kind=CapabilityKind.SKILL,
            provider="deployment-rollback",
            permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
            why=(
                "Prefer a project-scoped rollback workflow that executes the declared "
                "deployment recovery procedure without broad network access."
            ),
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "ai.evaluation": (
        RecommendationCandidate(
            kind=CapabilityKind.CLI_TOOL,
            provider="promptfoo",
            permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
            why="Prefer deterministic local evaluation scenarios before interactive review.",
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "security.threat-model": (
        RecommendationCandidate(
            kind=CapabilityKind.SKILL,
            provider="threat-modeling",
            permissions=(Permission.READ_PROJECT,),
            why="Prefer a read-only structured threat-model review of project trust boundaries.",
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "database.migration-testing": (
        RecommendationCandidate(
            kind=CapabilityKind.CLI_TOOL,
            provider="alembic",
            permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
            why=(
                "Use a deterministic migration CLI to exercise upgrade and rollback paths; "
                "choose the project-native equivalent when Alembic is not applicable."
            ),
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "api.contract-testing": (
        RecommendationCandidate(
            kind=CapabilityKind.CLI_TOOL,
            provider="schemathesis",
            permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
            why="Prefer deterministic schema-driven API contract checks.",
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "security.secret-scan": (
        RecommendationCandidate(
            kind=CapabilityKind.CLI_TOOL,
            provider="gitleaks",
            permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
            why="Prefer a local deterministic secret scan before any networked review.",
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "accessibility.review": (
        RecommendationCandidate(
            kind=CapabilityKind.CLI_TOOL,
            provider="axe-core",
            permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
            why="Prefer deterministic automated accessibility checks before manual review.",
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "repository.exploration": (
        RecommendationCandidate(
            kind=CapabilityKind.SKILL,
            provider="project-native-exploration",
            permissions=(Permission.READ_PROJECT,),
            why=(
                "Start with repository-native search, manifests, language metadata, "
                "and local indexes before discovering additional tooling."
            ),
            strength=RequirementStrength.REQUIRED,
        ),
    ),
    "quality.gates": (
        RecommendationCandidate(
            kind=CapabilityKind.CLI_TOOL,
            provider="project-native-quality",
            permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
            why=(
                "Compose the existing formatter, linter, typechecker, tests, and "
                "security checks before adding another product."
            ),
            strength=RequirementStrength.REQUIRED,
        ),
    ),
    "development.design": (
        RecommendationCandidate(
            kind=CapabilityKind.SKILL,
            provider="workflow-design",
            permissions=(Permission.READ_PROJECT,),
            why=(
                "Discover an installed workflow for comparing approaches and producing "
                "a verifiable implementation plan."
            ),
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
    "code.optimization": (
        RecommendationCandidate(
            kind=CapabilityKind.SKILL,
            provider="project-native-analysis",
            permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
            why=(
                "Use language- and framework-aware analysis backed by repository "
                "measurements; treat user-mentioned tools as discovery leads."
            ),
            strength=RequirementStrength.RECOMMENDED,
        ),
    ),
}

# These abstract domains intentionally have no universal provider recommendation: their
# correct implementation is project-specific, so naming a default would be misleading.
_NO_DEFAULT_RECOMMENDATIONS = frozenset(
    {
        "ai.prompt-review",
        "cli.help-review",
        "cli.integration-testing",
        "database.transaction-review",
        "observability.validation",
        "public-api.compatibility",
        "release.documentation",
    }
)


def _gap_recommendation(
    requirement: AbstractCapabilityRequirement,
    blueprint: Blueprint,
    remote_candidates: tuple[RemoteCandidate, ...],
    remote_evidence: Mapping[str, CandidateEvidence],
    rejected_remote_candidates: frozenset[str],
    policy: ResolverPolicy,
) -> CapabilityRecommendation | None:
    local_candidates = _LOCAL_GAP_RECOMMENDATIONS.get(requirement.capability)
    if local_candidates is None:
        # Known project-specific domains and unknown future domains deliberately keep
        # a bare GAP until a defensible default candidate is authored.
        assert (
            requirement.capability in _NO_DEFAULT_RECOMMENDATIONS
            or requirement.capability not in _LOCAL_GAP_RECOMMENDATIONS
        )
        return None
    candidates: tuple[RecommendationCandidate, ...]
    if not remote_candidates:
        candidates = local_candidates
    else:
        rejected_names = {
            candidate.name
            for candidate in remote_candidates
            if requirement.capability in candidate.provides
            and candidate.candidate_ref in rejected_remote_candidates
        }
        local_candidates = tuple(
            item for item in local_candidates if item.provider not in rejected_names
        )
        eligible = tuple(
            candidate
            for candidate in remote_candidates
            if requirement.capability in candidate.provides
            and candidate.candidate_ref not in rejected_remote_candidates
            and remote_org_filter_reason(candidate, policy) is None
        )
        ranked = tuple(
            sorted(
                rank_multi_source_candidates(
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
        maintenance_score=ranked.maintenance.score,
        popularity_score=ranked.popularity.score,
        total_score=ranked.total_score,
        score_explanations=(
            ranked.fit.explanation,
            ranked.trust.explanation,
            ranked.risk.explanation,
            ranked.maintenance.explanation,
            ranked.popularity.explanation,
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
