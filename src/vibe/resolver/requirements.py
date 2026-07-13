from __future__ import annotations

from pydantic import Field, model_validator

from vibe.models.base import VersionedModel
from vibe.practices.models import RequirementStrength


class RequirementOverride(VersionedModel):
    capability: str = Field(min_length=1)
    enabled: bool = True
    strength: RequirementStrength | None = None

    @model_validator(mode="after")
    def disabled_override_has_no_strength(self) -> RequirementOverride:
        if not self.enabled and self.strength is not None:
            raise ValueError("a disabled requirement override cannot set strength")
        return self


class AbstractCapabilityRequirement(VersionedModel):
    capability: str = Field(min_length=1)
    strength: RequirementStrength
    originating_packs: tuple[str, ...] = Field(min_length=1)
    originating_requirements: tuple[str, ...] = Field(min_length=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    verification: tuple[str, ...] = Field(min_length=1)
    overridden: bool = False
