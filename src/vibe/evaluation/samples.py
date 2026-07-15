"""Versioned offline task-routing sample contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from vibe.models.base import VersionedModel
from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    RiskLevel,
    ScopeLevel,
    TaskOperation,
)
from vibe.models.task import WorkflowMode
from vibe.workflows.scenarios import ScenarioId


class TaskDifficulty(StrEnum):
    SIMPLE = "simple"
    NORMAL = "normal"
    HIGH_RISK = "high-risk"


class CapabilitySource(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class ModelClassification(VersionedModel):
    scenario: ScenarioId
    scope: ScopeLevel
    data_sensitivity: DataSensitivity
    reversibility: Reversibility
    operations: frozenset[TaskOperation]
    risk_level: RiskLevel
    workflow_mode: WorkflowMode


class SampleCapability(VersionedModel):
    capability_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    provides: tuple[str, ...] = Field(min_length=1)
    permissions: tuple[str, ...] = ()
    phases: tuple[str, ...] = Field(min_length=1)
    source: CapabilitySource = CapabilitySource.LOCAL


class TaskSample(VersionedModel):
    sample_id: str = Field(min_length=1)
    difficulty: TaskDifficulty
    intent: str = Field(min_length=1)
    scenario: ScenarioId
    scope: tuple[str, ...] = Field(min_length=1)
    acceptance: tuple[str, ...] = Field(min_length=1)
    phase: str = Field(min_length=1)
    cross_module: bool = False
    candidates: tuple[SampleCapability, ...]
    tags: tuple[str, ...] = ()
    goal_change: str | None = None
    model_classification: ModelClassification | None = None
    expected_risk: RiskLevel
    expected_workflow: WorkflowMode
    expected_selected: tuple[str, ...] = ()
    expected_rejected: tuple[str, ...] = ()
    expected_permissions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def candidate_ids_are_unique(self) -> TaskSample:
        identifiers = [item.capability_id for item in self.candidates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("task sample capability IDs must be unique")
        return self


class TaskSampleSet(VersionedModel):
    samples: tuple[TaskSample, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def sample_ids_are_unique(self) -> TaskSampleSet:
        identifiers = [item.sample_id for item in self.samples]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("task sample IDs must be unique")
        return self
