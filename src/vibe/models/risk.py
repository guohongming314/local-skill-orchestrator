from enum import StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskDimension(StrEnum):
    SCOPE = "scope"
    DATA_SENSITIVITY = "data-sensitivity"
    REVERSIBILITY = "reversibility"
    OPERATIONS = "operations"


class RiskFactor(VersionedModel):
    dimension: RiskDimension
    level: RiskLevel
    rationale: str = Field(min_length=1)
    mitigations: tuple[str, ...] = ()


class Risk(VersionedModel):
    level: RiskLevel
    factors: tuple[RiskFactor, ...] = Field(min_length=1)
    requires_approval: bool = False
    rollback_required: bool = False