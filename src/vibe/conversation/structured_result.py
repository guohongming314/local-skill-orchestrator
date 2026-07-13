"""Validation, one-shot repair, revision, and locking for project model output."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum

from pydantic import Field, ValidationError, model_validator

from vibe.models.base import VersionedModel
from vibe.models.blueprint import Blueprint


class ValueSource(StrEnum):
    """Whether a structured value was inferred or confirmed by the user."""

    INFERRED = "inferred"
    CONFIRMED = "confirmed"


class StructuredProjectResult(VersionedModel):
    """A validated Blueprint plus review provenance and immutable decisions."""

    blueprint: Blueprint
    field_sources: dict[str, ValueSource]
    locked_decisions: frozenset[str] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def validate_decision_keys(self) -> StructuredProjectResult:
        fields = set(Blueprint.model_fields)
        unknown_sources = set(self.field_sources) - fields
        unknown_locks = set(self.locked_decisions) - fields
        if unknown_sources:
            raise ValueError(
                f"field_sources contains unknown Blueprint fields: {sorted(unknown_sources)}"
            )
        if unknown_locks:
            raise ValueError(
                f"locked_decisions contains unknown Blueprint fields: {sorted(unknown_locks)}"
            )
        return self


class StructuredResultError(ValueError):
    """Raised after structured output remains invalid after its one repair attempt."""

    def __init__(self, diagnostics: tuple[str, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("invalid structured project result: " + "; ".join(diagnostics))


class DecisionLockedError(ValueError):
    """Raised when a revision attempts to overwrite a locked decision."""


Repair = Callable[
    [Mapping[str, object], tuple[str, ...]],
    Mapping[str, object],
]


def parse_structured_result(
    payload: Mapping[str, object], *, repair: Repair | None = None
) -> StructuredProjectResult:
    """Validate output and permit exactly one caller-supplied repair attempt."""
    try:
        return StructuredProjectResult.model_validate(payload)
    except ValidationError as first_error:
        first_diagnostics = _diagnostics(first_error)
        if repair is None:
            raise StructuredResultError(first_diagnostics) from first_error
        repaired = repair(payload, first_diagnostics)
        try:
            return StructuredProjectResult.model_validate(repaired)
        except ValidationError as repaired_error:
            raise StructuredResultError(_diagnostics(repaired_error)) from repaired_error


def apply_revision(
    result: StructuredProjectResult,
    updates: Mapping[str, object],
    *,
    source: ValueSource,
) -> StructuredProjectResult:
    """Return a revised immutable result while honoring all decision locks."""
    locked = set(updates) & set(result.locked_decisions)
    if locked:
        names = ", ".join(sorted(locked))
        raise DecisionLockedError(f"cannot overwrite locked decision(s): {names}")

    blueprint_payload = result.blueprint.model_dump(mode="python")
    blueprint_payload.update(updates)
    try:
        blueprint = Blueprint.model_validate(blueprint_payload)
    except ValidationError as error:
        raise StructuredResultError(_diagnostics(error, prefix="blueprint")) from error
    field_sources = dict(result.field_sources)
    field_sources.update({key: source for key in updates})
    return result.model_copy(
        update={"blueprint": blueprint, "field_sources": field_sources}
    )


def lock_decisions(
    result: StructuredProjectResult, *field_names: str
) -> StructuredProjectResult:
    """Lock existing Blueprint fields against later model inference or revision."""
    unknown = set(field_names) - set(Blueprint.model_fields)
    if unknown:
        raise ValueError(f"cannot lock unknown Blueprint fields: {sorted(unknown)}")
    return result.model_copy(
        update={"locked_decisions": result.locked_decisions | frozenset(field_names)}
    )


def _diagnostics(error: ValidationError, *, prefix: str | None = None) -> tuple[str, ...]:
    diagnostics: list[str] = []
    for detail in error.errors(include_url=False):
        path = ".".join(str(part) for part in detail["loc"])
        if prefix is not None:
            path = f"{prefix}.{path}" if path else prefix
        diagnostics.append(f"{path or '<root>'}: {detail['msg']}")
    return tuple(diagnostics)
