from __future__ import annotations

from vibe.models.risk import RiskLevel
from vibe.remote.discovery import (
    DiscoveryService,
    DiscoveryStatus,
    SourceDiagnostic,
    SourceStatus,
    aggregate_discovery,
)
from vibe.remote.models import (
    CapabilityKind,
    PermissionLevel,
    Provenance,
    PublisherVerification,
    RemoteCandidate,
    SourceTier,
)
from vibe.remote.scoring import CandidateEvidence


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


class StaticSource:
    def __init__(self, source_id: str, result: SourceDiagnostic) -> None:
        self.source_id = source_id
        self._result = result

    def search(self, _capability_id: str) -> SourceDiagnostic:
        return self._result


def test_service_deduplicates_cross_listed_repository() -> None:
    github = candidate("browser").model_copy(
        update={
            "canonical_repository": "https://github.com/example/browser",
            "stars": 5000,
        }
    )
    skills = github.model_copy(
        update={
            "candidate_ref": "skills.sh:example/browser/browser",
            "source_tier": SourceTier.VERIFIED_PUBLISHER,
            "adoption": 20000,
            "official": True,
        }
    )
    service = DiscoveryService(
        (
            StaticSource(
                "github",
                diagnostic(
                    "github", SourceStatus.SUCCESS, candidates=(github,), matched_count=1
                ),
            ),
            StaticSource(
                "skills.sh",
                diagnostic(
                    "skills.sh", SourceStatus.SUCCESS, candidates=(skills,), matched_count=1
                ),
            ),
        )
    )

    report = service.discover(
        "browser.validation",
        approved=True,
        risk_level=RiskLevel.MEDIUM,
        evidence={github.candidate_ref: CandidateEvidence(maintenance=80)},
    )

    assert report.status is DiscoveryStatus.CANDIDATES_FOUND
    assert len(report.candidates) == 1
    assert report.candidates[0].adoption == 20000


def test_service_filters_archived_and_l4_candidates_despite_popularity() -> None:
    provenance = Provenance(
        source="github",
        digest="sha256:" + "a" * 64,
        source_verified=False,
        publisher_verified=False,
        publisher_verification=PublisherVerification.UNVERIFIED,
        digest_verified=True,
        permission_level=PermissionLevel.L4,
        reason="unsafe",
    )
    unsafe = candidate("popular-unsafe").model_copy(
        update={"stars": 1_000_000, "provenance": provenance}
    )
    archived = candidate("archived").model_copy(
        update={"stars": 900_000, "archived": True}
    )
    service = DiscoveryService(
        (
            StaticSource(
                "github",
                diagnostic(
                    "github",
                    SourceStatus.SUCCESS,
                    candidates=(unsafe, archived),
                    matched_count=2,
                ),
            ),
        )
    )

    report = service.discover(
        "browser.validation", approved=True, risk_level=RiskLevel.MEDIUM
    )

    assert report.status is DiscoveryStatus.ALL_FILTERED
    assert report.candidates == ()
