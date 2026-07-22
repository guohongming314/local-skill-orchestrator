from __future__ import annotations

from vibe.remote.discovery import (
    DiscoveryStatus,
    SourceDiagnostic,
    SourceStatus,
    aggregate_discovery,
)
from vibe.remote.models import CapabilityKind, RemoteCandidate, SourceTier


def candidate(name: str = "browser-tool") -> RemoteCandidate:
    return RemoteCandidate(
        candidate_ref=f"github:example/{name}@abc123",
        name=name,
        kind=CapabilityKind.AGENT_SKILL,
        provides=("browser.validation",),
        source_tier=SourceTier.COMMUNITY,
    )


def diagnostic(
    source: str,
    status: SourceStatus,
    *,
    candidates: tuple[RemoteCandidate, ...] = (),
    matched_count: int = 0,
    filtered_count: int = 0,
) -> SourceDiagnostic:
    return SourceDiagnostic(
        source_id=source,
        status=status,
        candidates=candidates,
        matched_count=matched_count,
        filtered_count=filtered_count,
    )


def test_discovery_not_requested_is_distinct_from_empty_search() -> None:
    report = aggregate_discovery(
        "browser.validation", approved=False, sources=(), diagnostics=()
    )

    assert report.status is DiscoveryStatus.NOT_REQUESTED
    assert report.attempted_sources == ()


def test_no_configured_sources_is_source_unavailable() -> None:
    report = aggregate_discovery(
        "browser.validation", approved=True, sources=(), diagnostics=()
    )

    assert report.status is DiscoveryStatus.SOURCE_UNAVAILABLE


def test_all_failed_sources_produce_search_failed() -> None:
    report = aggregate_discovery(
        "browser.validation",
        approved=True,
        sources=("github", "skills.sh"),
        diagnostics=(
            diagnostic("github", SourceStatus.RATE_LIMITED),
            diagnostic("skills.sh", SourceStatus.FAILED),
        ),
    )

    assert report.status is DiscoveryStatus.SEARCH_FAILED
    assert report.attempted_sources == ("github", "skills.sh")


def test_successful_empty_source_with_partial_failure_is_no_results() -> None:
    report = aggregate_discovery(
        "browser.validation",
        approved=True,
        sources=("github", "skills.sh"),
        diagnostics=(
            diagnostic("github", SourceStatus.SUCCESS),
            diagnostic("skills.sh", SourceStatus.RATE_LIMITED),
        ),
    )

    assert report.status is DiscoveryStatus.NO_RESULTS
    assert report.partial_failure is True


def test_matched_but_fully_filtered_results_are_all_filtered() -> None:
    report = aggregate_discovery(
        "browser.validation",
        approved=True,
        sources=("github",),
        diagnostics=(
            diagnostic(
                "github", SourceStatus.SUCCESS, matched_count=2, filtered_count=2
            ),
        ),
    )

    assert report.status is DiscoveryStatus.ALL_FILTERED


def test_eligible_candidates_produce_candidates_found() -> None:
    item = candidate()
    report = aggregate_discovery(
        "browser.validation",
        approved=True,
        sources=("github",),
        diagnostics=(
            diagnostic(
                "github",
                SourceStatus.SUCCESS,
                candidates=(item,),
                matched_count=1,
            ),
        ),
    )

    assert report.status is DiscoveryStatus.CANDIDATES_FOUND
    assert report.candidates == (item,)
