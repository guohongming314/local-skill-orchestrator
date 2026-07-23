"""Consistent evidence-backed recommendation explanations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecommendationEvidence:
    requirement: str
    provider: str
    need_reason: str
    fit_reasons: tuple[str, ...]
    permissions: tuple[str, ...]
    verification: str
    alternative: str
    alternative_reason: str


def explain_candidate(evidence: RecommendationEvidence) -> str:
    fit = "; ".join(evidence.fit_reasons) or "no verified fit evidence"
    permissions = ", ".join(evidence.permissions) or "none"
    return (
        f"Need ({evidence.requirement}): {evidence.need_reason} "
        f"Provider: {evidence.provider}. Fit: {fit}. Permissions: {permissions}. "
        f"Verification: {evidence.verification}. Alternative: {evidence.alternative} - "
        f"{evidence.alternative_reason}."
    )
