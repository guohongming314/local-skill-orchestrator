from pydantic import Field, model_validator

from vibe.models.base import VersionedModel


class SourceReference(VersionedModel):
    source_id: str = Field(min_length=1)
    digest: str = Field(min_length=8)


class ContextCapsule(VersionedModel):
    task_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    scope: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    current_phase: str = Field(min_length=1)
    selected_capability_ids: tuple[str, ...] = ()
    deferred_capability_ids: tuple[str, ...] = ()
    rejected_capability_ids: tuple[str, ...] = ()
    sources: tuple[SourceReference, ...] = Field(min_length=1)
    invalidation_conditions: tuple[str, ...] = Field(min_length=1)
    token_budget: int = Field(gt=0)

    @model_validator(mode="after")
    def capability_sets_are_disjoint(self) -> "ContextCapsule":
        groups = [
            set(self.selected_capability_ids),
            set(self.deferred_capability_ids),
            set(self.rejected_capability_ids),
        ]
        if any(groups[index] & groups[other] for index in range(3) for other in range(index)):
            raise ValueError("selected, deferred, and rejected capabilities must be disjoint")
        return self

