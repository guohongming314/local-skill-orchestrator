from enum import StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel


class LifecycleStage(StrEnum):
    EXPLORATION = "exploration"
    ACTIVE_DEVELOPMENT = "active-development"
    MAINTENANCE = "maintenance"
    PRODUCTION = "production"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProjectConstraint(VersionedModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    locked: bool = False


class Blueprint(VersionedModel):
    project_name: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    lifecycle_stage: LifecycleStage
    risk_level: RiskLevel
    target_platforms: tuple[str, ...] = ("codex",)
    constraints: tuple[ProjectConstraint, ...] = ()
    preferences: dict[str, str | bool | int] = Field(default_factory=dict)
    repository_digest: str = Field(min_length=8)

