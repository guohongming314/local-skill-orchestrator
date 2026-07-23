"""Pure installation-review readiness evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewReadiness:
    ready: bool
    next_action: str
    blocking_requirements: tuple[str, ...] = ()
    unknown_permissions: tuple[str, ...] = ()


def evaluate_review_readiness(
    *,
    required_gaps: tuple[str, ...],
    recommended_gaps: tuple[str, ...],
    discovery_status: Mapping[str, str],
    candidate_decisions: Mapping[str, str],
    unknown_permissions: tuple[str, ...],
) -> ReviewReadiness:
    decided = {"accept", "reject", "defer"}
    default_decision = candidate_decisions.get("*")

    def decision_for(requirement: str) -> str | None:
        return candidate_decisions.get(requirement, default_decision)

    unresolved_required = tuple(
        item for item in required_gaps if decision_for(item) not in decided
    )
    not_requested = tuple(
        item
        for item in (*required_gaps, *recommended_gaps)
        if discovery_status.get(item) == "not-requested"
        and decision_for(item) not in {"reject", "defer"}
    )
    blocking = tuple(dict.fromkeys((*unresolved_required, *not_requested)))
    if blocking:
        return ReviewReadiness(
            ready=False,
            next_action="request-discovery-decision",
            blocking_requirements=blocking,
            unknown_permissions=unknown_permissions,
        )
    unresolved_candidates = tuple(
        item
        for item in (*required_gaps, *recommended_gaps)
        if discovery_status.get(item) == "candidates-found"
        and decision_for(item) not in decided
    )
    if unresolved_candidates:
        return ReviewReadiness(
            ready=False,
            next_action="request-candidate-decision",
            blocking_requirements=tuple(dict.fromkeys(unresolved_candidates)),
            unknown_permissions=unknown_permissions,
        )
    return ReviewReadiness(
        ready=not unknown_permissions,
        next_action=(
            "review-installation" if not unknown_permissions else "request-permission-decision"
        ),
        unknown_permissions=unknown_permissions,
    )
