"""Deterministic, project-local calibration of recommendation strength."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from vibe.models.base import VersionedModel
from vibe.practices.models import RequirementStrength
from vibe.resolver.requirements import OverrideProvenance, RequirementOverride

_UNUSED_RECOMMENDATION_THRESHOLD = 3
_STATE_PATH = Path(".ai-project/calibration.yaml")


class CalibrationOutcome(VersionedModel):
    """The outcome fields needed by deterministic calibration rules."""

    task_id: str = Field(min_length=1)
    unused_recommendations: tuple[str, ...] = ()


class CalibrationSuggestion(VersionedModel):
    """An explainable strength change that must be confirmed before use."""

    suggestion_id: str = Field(min_length=8)
    capability: str = Field(min_length=1)
    current_strength: RequirementStrength
    proposed_strength: RequirementStrength
    rule: str = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)
    provenance: OverrideProvenance = OverrideProvenance.OUTCOME_CALIBRATION


class CalibrationDecision(VersionedModel):
    suggestion: CalibrationSuggestion
    status: Literal["confirmed", "rejected"]


class CalibrationState(VersionedModel):
    decisions: tuple[CalibrationDecision, ...] = ()


def pending_suggestions(
    root: Path,
    outcomes: tuple[CalibrationOutcome, ...],
) -> tuple[CalibrationSuggestion, ...]:
    """Return deterministic suggestions not already confirmed or rejected."""
    decided = {item.suggestion.suggestion_id for item in _load_state(root).decisions}
    unused: dict[str, list[str]] = defaultdict(list)
    for outcome in outcomes:
        for capability in outcome.unused_recommendations:
            unused[capability].append(outcome.task_id)

    suggestions = []
    for capability in sorted(unused):
        evidence = tuple(dict.fromkeys(unused[capability]))
        if len(evidence) < _UNUSED_RECOMMENDATION_THRESHOLD:
            continue
        suggestion = _demotion(capability, evidence)
        if suggestion.suggestion_id not in decided:
            suggestions.append(suggestion)
    return tuple(suggestions)


def confirm_suggestion(root: Path, suggestion: CalibrationSuggestion) -> None:
    """Persist explicit user confirmation of a project-scoped override."""
    _record_decision(root, suggestion, "confirmed")


def reject_suggestion(root: Path, suggestion: CalibrationSuggestion) -> None:
    """Persist explicit user rejection so the same rule is not proposed again."""
    _record_decision(root, suggestion, "rejected")


def load_confirmed_overrides(root: Path) -> tuple[RequirementOverride, ...]:
    """Load only confirmed calibration decisions for future resolution runs."""
    overrides = (
        RequirementOverride(
            capability=decision.suggestion.capability,
            strength=decision.suggestion.proposed_strength,
            provenance=OverrideProvenance.OUTCOME_CALIBRATION,
        )
        for decision in _load_state(root).decisions
        if decision.status == "confirmed"
    )
    return tuple(sorted(overrides, key=lambda item: item.capability))


def _demotion(capability: str, evidence: tuple[str, ...]) -> CalibrationSuggestion:
    rule = f"unused-recommendation-at-least-{_UNUSED_RECOMMENDATION_THRESHOLD}"
    identity = f"{capability}\0{rule}\0recommended\0optional"
    return CalibrationSuggestion(
        suggestion_id=hashlib.sha256(identity.encode()).hexdigest()[:16],
        capability=capability,
        current_strength=RequirementStrength.RECOMMENDED,
        proposed_strength=RequirementStrength.OPTIONAL,
        rule=rule,
        evidence=evidence,
    )


def _record_decision(
    root: Path,
    suggestion: CalibrationSuggestion,
    status: Literal["confirmed", "rejected"],
) -> None:
    state = _load_state(root)
    decisions = {
        item.suggestion.suggestion_id: item
        for item in state.decisions
    }
    decisions[suggestion.suggestion_id] = CalibrationDecision(
        suggestion=suggestion,
        status=status,
    )
    _write_state(
        root,
        CalibrationState(
            decisions=tuple(decisions[key] for key in sorted(decisions))
        ),
    )


def _load_state(root: Path) -> CalibrationState:
    target = root / _STATE_PATH
    if not target.is_file():
        return CalibrationState()
    payload = yaml.safe_load(target.read_text(encoding="utf-8-sig"))
    return CalibrationState.model_validate(payload)


def _write_state(root: Path, state: CalibrationState) -> None:
    target = root / _STATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(state.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(target)
