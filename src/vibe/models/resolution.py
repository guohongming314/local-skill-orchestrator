from enum import StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel


class ResolutionStatus(StrEnum):
    SELECTED = "selected"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    GAP = "gap"


class CapabilityResolution(VersionedModel):
    requirement: str = Field(min_length=1)
    status: ResolutionStatus
    capability_id: str | None = None
    reason: str = Field(min_length=1)


class ResolutionPlan(VersionedModel):
    blueprint_digest: str = Field(min_length=8)
    inventory_digest: str = Field(min_length=8)
    resolutions: tuple[CapabilityResolution, ...]

