from enum import StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel
from vibe.models.blueprint import RiskLevel


class WorkflowMode(StrEnum):
    FAST = "fast"
    STANDARD = "standard"
    RIGOROUS = "rigorous"


class TaskPhase(VersionedModel):
    phase_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    completion_conditions: tuple[str, ...] = Field(min_length=1)
    capability_ids: tuple[str, ...] = ()
    requires_approval: bool = False


class TaskPlan(VersionedModel):
    task_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    risk_level: RiskLevel
    workflow_mode: WorkflowMode
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    phases: tuple[TaskPhase, ...] = Field(min_length=1)

