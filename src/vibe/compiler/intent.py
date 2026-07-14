"""Explicit task intent accepted by the deterministic context compiler."""

from __future__ import annotations

from pydantic import Field, field_validator

from vibe.models.base import VersionedModel
from vibe.workflows.scenarios import ScenarioId


class TaskIntent(VersionedModel):
    """Structured task input; callers classify intent without model inference."""

    task_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    scenario: ScenarioId
    scope: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    cross_module: bool = False

    @field_validator("scope")
    @classmethod
    def normalize_scope(cls, scope: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(
            sorted({item.strip().replace("\\", "/") for item in scope if item.strip()})
        )
        if not normalized:
            raise ValueError("scope must contain at least one non-empty path")
        return normalized
