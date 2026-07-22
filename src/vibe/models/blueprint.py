from enum import StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel
from vibe.models.decisions import ProjectDecisions
from vibe.models.risk import RiskLevel as RiskLevel


class LifecycleStage(StrEnum):
    EXPLORATION = "exploration"
    ACTIVE_DEVELOPMENT = "active-development"
    MAINTENANCE = "maintenance"
    PRODUCTION = "production"


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
    decisions: ProjectDecisions = Field(default_factory=ProjectDecisions)
