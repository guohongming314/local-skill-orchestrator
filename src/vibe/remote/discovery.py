"""Deterministic aggregation for approved multi-source capability discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from vibe.models.base import VersionedModel
from vibe.models.risk import RiskLevel
from vibe.remote.models import PermissionLevel, RemoteCandidate, SourceTier
from vibe.remote.scoring import (
    CandidateEvidence,
    ScoringContext,
    rank_multi_source_candidates,
)


class DiscoveryStatus(StrEnum):
    NOT_REQUESTED = "not-requested"
    SOURCE_UNAVAILABLE = "source-unavailable"
    SEARCH_FAILED = "search-failed"
    NO_RESULTS = "no-results"
    ALL_FILTERED = "all-filtered"
    CANDIDATES_FOUND = "candidates-found"
    INSTALLATION_DEFERRED = "installation-deferred"
    INSTALLATION_REJECTED = "installation-rejected"


class SourceStatus(StrEnum):
    SUCCESS = "success"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    RATE_LIMITED = "rate-limited"
    UNAUTHORIZED = "unauthorized"
    CACHED = "cached"


class SourceDiagnostic(VersionedModel):
    source_id: str = Field(min_length=1)
    status: SourceStatus
    candidates: tuple[RemoteCandidate, ...] = ()
    matched_count: int = Field(default=0, ge=0)
    filtered_count: int = Field(default=0, ge=0)
    message: str | None = None


class DiscoveryReport(VersionedModel):
    requirement: str = Field(min_length=1)
    status: DiscoveryStatus
    attempted_sources: tuple[str, ...] = ()
    diagnostics: tuple[SourceDiagnostic, ...] = ()
    candidates: tuple[RemoteCandidate, ...] = ()
    partial_failure: bool = False


class DiscoverySource(Protocol):
    source_id: str

    def search(self, capability_id: str) -> SourceDiagnostic: ...


class DiscoveryService:
    """Query approved sources, filter unsafe records, deduplicate, and rank results."""

    def __init__(self, sources: Sequence[DiscoverySource]) -> None:
        self._sources = tuple(sources)

    def discover(
        self,
        requirement: str,
        *,
        approved: bool,
        risk_level: RiskLevel,
        target_platforms: tuple[str, ...] = (),
        evidence: Mapping[str, CandidateEvidence] | None = None,
    ) -> DiscoveryReport:
        source_ids = tuple(source.source_id for source in self._sources)
        if not approved or not self._sources:
            return aggregate_discovery(
                requirement,
                approved=approved,
                sources=source_ids,
                diagnostics=(),
            )
        diagnostics = tuple(source.search(requirement) for source in self._sources)
        successful = tuple(
            item
            for item in diagnostics
            if item.status in {SourceStatus.SUCCESS, SourceStatus.CACHED}
        )
        merged = _deduplicate(
            tuple(candidate for item in successful for candidate in item.candidates)
        )
        safe = tuple(candidate for candidate in merged if not _blocked(candidate))
        ranked = rank_multi_source_candidates(
            safe,
            ScoringContext(
                requirement=requirement,
                target_platforms=target_platforms,
                project_risk_level=risk_level,
            ),
            evidence=evidence or {},
        )
        candidates = tuple(item.candidate for item in ranked[:3])
        if candidates:
            status = DiscoveryStatus.CANDIDATES_FOUND
        elif successful and any(item.matched_count for item in successful):
            status = DiscoveryStatus.ALL_FILTERED
        elif successful:
            status = DiscoveryStatus.NO_RESULTS
        else:
            status = DiscoveryStatus.SEARCH_FAILED
        successful_count = len(successful)
        return DiscoveryReport(
            requirement=requirement,
            status=status,
            attempted_sources=source_ids,
            diagnostics=diagnostics,
            candidates=candidates,
            partial_failure=0 < successful_count < len(diagnostics),
        )


def aggregate_discovery(
    requirement: str,
    *,
    approved: bool,
    sources: tuple[str, ...],
    diagnostics: tuple[SourceDiagnostic, ...],
) -> DiscoveryReport:
    """Derive one truthful overall state from per-source outcomes."""
    if not approved:
        status = DiscoveryStatus.NOT_REQUESTED
    elif not sources:
        status = DiscoveryStatus.SOURCE_UNAVAILABLE
    else:
        successful = tuple(
            item
            for item in diagnostics
            if item.status in {SourceStatus.SUCCESS, SourceStatus.CACHED}
        )
        candidates = tuple(candidate for item in successful for candidate in item.candidates)
        if candidates:
            status = DiscoveryStatus.CANDIDATES_FOUND
        elif not successful:
            status = DiscoveryStatus.SEARCH_FAILED
        elif sum(item.matched_count for item in successful) > 0 and sum(
            item.filtered_count for item in successful
        ) >= sum(item.matched_count for item in successful):
            status = DiscoveryStatus.ALL_FILTERED
        else:
            status = DiscoveryStatus.NO_RESULTS
    candidates = tuple(
        candidate
        for item in diagnostics
        if item.status in {SourceStatus.SUCCESS, SourceStatus.CACHED}
        for candidate in item.candidates
    )
    successful_count = sum(
        item.status in {SourceStatus.SUCCESS, SourceStatus.CACHED} for item in diagnostics
    )
    return DiscoveryReport(
        requirement=requirement,
        status=status,
        attempted_sources=sources if approved else (),
        diagnostics=diagnostics,
        candidates=candidates,
        partial_failure=0 < successful_count < len(diagnostics),
    )


def _blocked(candidate: RemoteCandidate) -> bool:
    if candidate.archived:
        return True
    provenance = candidate.provenance
    return provenance is not None and provenance.permission_level is PermissionLevel.L4


def _deduplicate(candidates: tuple[RemoteCandidate, ...]) -> tuple[RemoteCandidate, ...]:
    by_identity: dict[str, RemoteCandidate] = {}
    unkeyed: list[RemoteCandidate] = []
    for candidate in candidates:
        identity = _identity(candidate)
        if identity is None:
            unkeyed.append(candidate)
            continue
        existing = by_identity.get(identity)
        by_identity[identity] = (
            candidate if existing is None else _merge(existing, candidate)
        )
    return tuple(
        sorted((*by_identity.values(), *unkeyed), key=lambda item: item.candidate_ref)
    )


def _identity(candidate: RemoteCandidate) -> str | None:
    if candidate.canonical_repository:
        return candidate.canonical_repository.rstrip("/").casefold()
    if candidate.cross_source_ref:
        return candidate.cross_source_ref.casefold()
    if candidate.digest:
        return candidate.digest.casefold()
    return None


def _merge(left: RemoteCandidate, right: RemoteCandidate) -> RemoteCandidate:
    trust = {
        SourceTier.OFFICIAL: 4,
        SourceTier.VERIFIED_PUBLISHER: 3,
        SourceTier.COMMUNITY: 2,
        SourceTier.GENERAL_SEARCH: 1,
    }
    primary, other = (
        (left, right)
        if trust[left.source_tier] >= trust[right.source_tier]
        else (right, left)
    )
    return primary.model_copy(
        update={
            "stars": max(left.stars, right.stars),
            "forks": max(left.forks, right.forks),
            "adoption": max(left.adoption, right.adoption),
            "weekly_adoption": max(left.weekly_adoption, right.weekly_adoption),
            "official": left.official or right.official,
            "canonical_repository": (
                primary.canonical_repository or other.canonical_repository
            ),
            "cross_source_ref": primary.cross_source_ref or other.cross_source_ref,
        }
    )
