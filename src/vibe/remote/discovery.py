"""Deterministic aggregation for approved multi-source capability discovery."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel
from vibe.remote.models import RemoteCandidate


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
