"""Deterministic policy filtering and explainable scoring for remote candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from vibe.models.risk import RiskLevel
from vibe.remote.models import PermissionLevel, RemoteCandidate, SourceTier

_PERMISSION_ORDER = {
    PermissionLevel.L0: 0,
    PermissionLevel.L1: 1,
    PermissionLevel.L2: 2,
    PermissionLevel.L3: 3,
    PermissionLevel.L4: 4,
}
_PERMISSION_CEILING = {
    RiskLevel.LOW: PermissionLevel.L1,
    RiskLevel.MEDIUM: PermissionLevel.L2,
    RiskLevel.HIGH: PermissionLevel.L3,
    RiskLevel.CRITICAL: PermissionLevel.L3,
}
_SOURCE_TRUST = {
    SourceTier.OFFICIAL: 60,
    SourceTier.VERIFIED_PUBLISHER: 50,
    SourceTier.COMMUNITY: 30,
    SourceTier.GENERAL_SEARCH: 10,
}
_RISK_CATEGORIES = (
    (25, ("execute-command", "command-execution")),
    (30, ("credentials", "credential-access")),
    (25, ("network-write", "external-write")),
    (20, ("hook-installation", "install-hook")),
)


@dataclass(frozen=True)
class CandidateEvidence:
    """Project and scanner evidence not declared by the remote source."""

    platforms: tuple[str, ...] = ()
    project_fact_matches: tuple[str, ...] = ()
    maintenance: int = 0
    adoption: int = 0
    scan_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoringContext:
    requirement: str
    target_platforms: tuple[str, ...]
    project_risk_level: RiskLevel
    rejected_capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ExplainedScore:
    score: int
    explanation: str


@dataclass(frozen=True)
class RankedCandidate:
    candidate: RemoteCandidate
    fit: ExplainedScore
    trust: ExplainedScore
    risk: ExplainedScore
    adoption: int


_EMPTY_EVIDENCE: Mapping[str, CandidateEvidence] = MappingProxyType({})


def rank_candidates(
    candidates: tuple[RemoteCandidate, ...],
    context: ScoringContext,
    *,
    evidence: Mapping[str, CandidateEvidence] = _EMPTY_EVIDENCE,
) -> tuple[RankedCandidate, ...]:
    """Filter candidates by hard policy, then rank by fit, trust, risk, and adoption."""

    ranked = []
    for candidate in candidates:
        candidate_evidence = evidence.get(candidate.candidate_ref, CandidateEvidence())
        if _hard_filter_reason(candidate, context, candidate_evidence) is not None:
            continue
        ranked.append(_score_candidate(candidate, context, candidate_evidence))
    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                -item.fit.score,
                -item.trust.score,
                item.risk.score,
                -item.adoption,
                item.candidate.candidate_ref,
            ),
        )
    )


def _hard_filter_reason(
    candidate: RemoteCandidate,
    context: ScoringContext,
    evidence: CandidateEvidence,
) -> str | None:
    if context.requirement in context.rejected_capabilities:
        return "project policy rejected the required capability"
    if evidence.platforms and not set(evidence.platforms).intersection(context.target_platforms):
        return "candidate is incompatible with the target platforms"
    provenance = candidate.provenance
    if provenance is None:
        return None
    if provenance.permission_level is PermissionLevel.L4:
        return "L4 provenance is blocked"
    ceiling = _PERMISSION_CEILING[context.project_risk_level]
    if _PERMISSION_ORDER[provenance.permission_level] > _PERMISSION_ORDER[ceiling]:
        return "candidate exceeds the blueprint permission ceiling"
    return None


def _score_candidate(
    candidate: RemoteCandidate,
    context: ScoringContext,
    evidence: CandidateEvidence,
) -> RankedCandidate:
    capability_points = 70 if context.requirement in candidate.provides else 0
    platform_points = 10 if evidence.platforms else 0
    fact_points = min(20, len(set(evidence.project_fact_matches)) * 5)
    fit_score = capability_points + platform_points + fact_points
    fit = ExplainedScore(
        score=fit_score,
        explanation=(
            f"fit={fit_score} (capability={capability_points}, "
            f"platform={platform_points}, project-facts={fact_points})"
        ),
    )

    provenance = candidate.provenance
    publisher_points = 20 if provenance is not None and provenance.publisher_verified else 0
    digest_points = 10 if provenance is not None and provenance.digest_verified else 0
    maintenance_points = max(0, min(10, evidence.maintenance // 10))
    source_points = _SOURCE_TRUST[candidate.source_tier]
    trust_score = source_points + publisher_points + digest_points + maintenance_points
    trust = ExplainedScore(
        score=trust_score,
        explanation=(
            f"trust={trust_score} (source-tier={source_points}, "
            f"publisher={publisher_points}, digest={digest_points}, "
            f"maintenance={maintenance_points})"
        ),
    )

    declared = tuple(item.lower() for item in candidate.permissions_as_declared)
    flags = tuple(item.lower() for item in evidence.scan_flags)
    risk_terms = (*declared, *flags)
    risk_score = min(
        100,
        sum(
            weight
            for weight, aliases in _RISK_CATEGORIES
            if any(alias in term for alias in aliases for term in risk_terms)
        ),
    )
    risk = ExplainedScore(
        score=risk_score,
        explanation=(
            f"risk={risk_score} (declared={', '.join(declared) or 'none'}, "
            f"scan={', '.join(flags) or 'none'})"
        ),
    )
    return RankedCandidate(
        candidate=candidate,
        fit=fit,
        trust=trust,
        risk=risk,
        adoption=max(0, evidence.adoption),
    )
