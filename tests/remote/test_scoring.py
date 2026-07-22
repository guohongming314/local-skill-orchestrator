from __future__ import annotations

import hashlib

import pytest

from vibe.models.risk import RiskLevel
from vibe.remote.models import (
    CapabilityKind,
    PermissionLevel,
    Provenance,
    PublisherVerification,
    RemoteCandidate,
    SourceTier,
)
from vibe.remote.scoring import (
    CandidateEvidence,
    ScoringContext,
    rank_candidates,
    rank_multi_source_candidates,
)


def candidate(
    name: str,
    *,
    source_tier: SourceTier = SourceTier.OFFICIAL,
    permission_level: PermissionLevel = PermissionLevel.L1,
    publisher_verified: bool = True,
    permissions: tuple[str, ...] = (),
) -> RemoteCandidate:
    digest = "sha256:" + hashlib.sha256(name.encode()).hexdigest()
    verification = (
        PublisherVerification.ALLOWLIST
        if publisher_verified
        else PublisherVerification.UNVERIFIED
    )
    return RemoteCandidate(
        candidate_ref=f"registry:{name}@1.0.0",
        name=name,
        kind=CapabilityKind.AGENT_SKILL,
        provides=("browser-automation",),
        version="1.0.0",
        digest=digest,
        publisher=f"{name} publisher",
        permissions_as_declared=permissions,
        source_tier=source_tier,
        provenance=Provenance(
            source="fixture-registry",
            publisher=f"{name} publisher",
            digest=digest,
            source_verified=source_tier
            in {SourceTier.OFFICIAL, SourceTier.VERIFIED_PUBLISHER},
            publisher_verified=publisher_verified,
            publisher_verification=verification,
            digest_verified=True,
            permission_level=permission_level,
            reason="fixture provenance",
        ),
    )


def context(**changes: object) -> ScoringContext:
    values: dict[str, object] = {
        "requirement": "browser-automation",
        "target_platforms": ("codex",),
        "project_risk_level": RiskLevel.MEDIUM,
    }
    values.update(changes)
    return ScoringContext(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("blocked", "scoring_context", "evidence", "expected"),
    [
        (
            candidate("wrong-platform"),
            context(),
            CandidateEvidence(platforms=("claude",)),
            ["allowed"],
        ),
        (
            candidate("project-rejected"),
            context(rejected_capabilities=frozenset({"browser-automation"})),
            CandidateEvidence(platforms=("codex",)),
            [],
        ),
        (
            candidate("above-ceiling", permission_level=PermissionLevel.L2),
            context(project_risk_level=RiskLevel.LOW),
            CandidateEvidence(platforms=("codex",)),
            ["allowed"],
        ),
        (
            candidate("l4-provenance", permission_level=PermissionLevel.L4),
            context(project_risk_level=RiskLevel.CRITICAL),
            CandidateEvidence(platforms=("codex",)),
            ["allowed"],
        ),
    ],
)
def test_policy_filtered_candidate_is_never_ranked(
    blocked: RemoteCandidate,
    scoring_context: ScoringContext,
    evidence: CandidateEvidence,
    expected: list[str],
) -> None:
    allowed = candidate("allowed")

    ranked = rank_candidates(
        (blocked, allowed),
        scoring_context,
        evidence={
            blocked.candidate_ref: evidence,
            allowed.candidate_ref: CandidateEvidence(platforms=("codex",)),
        },
    )

    assert [item.candidate.name for item in ranked] == expected


def test_high_popularity_low_trust_candidate_loses_to_verified_alternative() -> None:
    popular = candidate(
        "popular-community",
        source_tier=SourceTier.COMMUNITY,
        publisher_verified=False,
    )
    verified = candidate("verified-official")

    ranked = rank_candidates(
        (popular, verified),
        context(),
        evidence={
            popular.candidate_ref: CandidateEvidence(
                platforms=("codex",), adoption=1_000_000, maintenance=50
            ),
            verified.candidate_ref: CandidateEvidence(
                platforms=("codex",), adoption=10, maintenance=50
            ),
        },
    )

    assert [item.candidate.name for item in ranked] == [
        "verified-official",
        "popular-community",
    ]
    assert ranked[0].trust.score > ranked[1].trust.score
    assert all(item.fit.explanation for item in ranked)
    assert all(item.trust.explanation for item in ranked)
    assert all(item.risk.explanation for item in ranked)


def test_tie_is_broken_by_adoption_deterministically() -> None:
    first = candidate("first")
    adopted = candidate("adopted")
    scoring_evidence = {
        first.candidate_ref: CandidateEvidence(
            platforms=("codex",), adoption=10, maintenance=50
        ),
        adopted.candidate_ref: CandidateEvidence(
            platforms=("codex",), adoption=20, maintenance=50
        ),
    }

    expected = ["adopted", "first"]
    assert [
        item.candidate.name
        for item in rank_candidates((first, adopted), context(), evidence=scoring_evidence)
    ] == expected
    assert [
        item.candidate.name
        for item in rank_candidates((adopted, first), context(), evidence=scoring_evidence)
    ] == expected


def test_multi_source_popularity_is_bounded_and_cannot_overrule_trust() -> None:
    popular = candidate(
        "popular-community",
        source_tier=SourceTier.COMMUNITY,
        publisher_verified=False,
    ).model_copy(update={"stars": 1_000_000, "adoption": 1_000_000})
    trusted = candidate("trusted-official").model_copy(
        update={"stars": 500, "adoption": 500, "official": True}
    )

    ranked = rank_multi_source_candidates(
        (popular, trusted),
        context(),
        evidence={
            popular.candidate_ref: CandidateEvidence(
                platforms=("codex",), maintenance=20
            ),
            trusted.candidate_ref: CandidateEvidence(
                platforms=("codex",), maintenance=90
            ),
        },
    )

    assert ranked[0].candidate.name == "trusted-official"
    assert all(item.popularity.score <= 100 for item in ranked)
    assert all(item.total_score <= 100 for item in ranked)
