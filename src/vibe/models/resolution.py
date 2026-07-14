from enum import StrEnum

from pydantic import Field, model_validator

from vibe.models.base import VersionedModel
from vibe.models.capability import CapabilityKind, Permission
from vibe.practices.models import RequirementStrength


class ResolutionStatus(StrEnum):
    SELECTED = "selected"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    GAP = "gap"


class RecommendationCandidate(VersionedModel):
    kind: CapabilityKind
    provider: str = Field(min_length=1)
    permissions: tuple[Permission, ...]
    why: str = Field(min_length=1)
    strength: RequirementStrength
    candidate_ref: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    permission_level: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    approval_required: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    fit_score: int | None = Field(default=None, exclude_if=lambda value: value is None)
    trust_score: int | None = Field(default=None, exclude_if=lambda value: value is None)
    risk_score: int | None = Field(default=None, exclude_if=lambda value: value is None)
    score_explanations: tuple[str, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    risk_flags: tuple[str, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class CapabilityRecommendation(VersionedModel):
    why: str = Field(min_length=1)
    candidates: tuple[RecommendationCandidate, ...] = Field(min_length=1)


class CapabilityResolution(VersionedModel):
    requirement: str = Field(min_length=1)
    status: ResolutionStatus
    capability_id: str | None = None
    reason: str = Field(min_length=1)
    recommendation: CapabilityRecommendation | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def selected_resolution_has_capability(self) -> "CapabilityResolution":
        if self.status is ResolutionStatus.SELECTED and self.capability_id is None:
            raise ValueError("selected resolution requires capability_id")
        return self


class ResolutionPlan(VersionedModel):
    blueprint_digest: str = Field(min_length=8)
    inventory_digest: str = Field(min_length=8)
    resolutions: tuple[CapabilityResolution, ...]

