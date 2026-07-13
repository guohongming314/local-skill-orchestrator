from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from vibe.models.base import VersionedModel


class MatchOperator(StrEnum):
    EQUALS = "equals"
    CONTAINS = "contains"
    IN = "in"
    EXISTS = "exists"


class MatchCondition(VersionedModel):
    field: str = Field(min_length=1)
    operator: MatchOperator = MatchOperator.EQUALS
    value: str | bool | tuple[str, ...]


class MatchRule(VersionedModel):
    all_of: tuple[MatchCondition, ...] = ()
    any_of: tuple[MatchCondition, ...] = ()
    none_of: tuple[MatchCondition, ...] = ()


class RequirementStrength(StrEnum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class CapabilityRequirement(VersionedModel):
    requirement_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    capability: str = Field(min_length=1)
    strength: RequirementStrength
    rationale: str = Field(min_length=1)
    verification: tuple[str, ...] = Field(min_length=1)


class PracticeException(VersionedModel):
    exception_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    when: MatchRule
    suppress_requirements: tuple[str, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ConflictResolution(StrEnum):
    PREFER_SELF = "prefer-self"
    PREFER_OTHER = "prefer-other"
    ERROR = "error"


class PackConflict(VersionedModel):
    pack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    resolution: ConflictResolution
    rationale: str = Field(min_length=1)


class PracticePack(VersionedModel):
    pack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    priority: int = Field(ge=0)
    match: MatchRule
    requirements: tuple[CapabilityRequirement, ...] = Field(min_length=1)
    exceptions: tuple[PracticeException, ...] = ()
    conflicts: tuple[PackConflict, ...] = ()

    @model_validator(mode="after")
    def references_are_valid(self) -> PracticePack:
        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement_id values must be unique within a pack")
        known = set(requirement_ids)
        for exception in self.exceptions:
            unknown = set(exception.suppress_requirements) - known
            if unknown:
                raise ValueError(
                    f"exception {exception.exception_id!r} references unknown requirements: "
                    f"{sorted(unknown)!r}"
                )
        return self

    @classmethod
    def migrate(cls, data: dict[str, Any]) -> PracticePack:
        return cls.model_validate(data)
