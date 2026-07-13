from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from vibe.models.blueprint import Blueprint
from vibe.models.repository import RepositorySnapshot
from vibe.practices.matcher import matches
from vibe.practices.models import ConflictResolution, PracticePack, RequirementStrength
from vibe.resolver.requirements import AbstractCapabilityRequirement, RequirementOverride


class PracticeConflictError(ValueError):
    """Raised when two applicable packs declare an unresolvable policy conflict."""


@dataclass(frozen=True)
class _Contribution:
    pack_id: str
    requirement_id: str
    capability: str
    strength: RequirementStrength
    rationale: str
    verification: tuple[str, ...]


_STRENGTH_RANK = {
    RequirementStrength.OPTIONAL: 0,
    RequirementStrength.RECOMMENDED: 1,
    RequirementStrength.REQUIRED: 2,
}


def evaluate_practice_packs(
    packs: Iterable[PracticePack],
    blueprint: Blueprint,
    repository: RepositorySnapshot,
    *,
    overrides: Iterable[RequirementOverride] = (),
) -> tuple[AbstractCapabilityRequirement, ...]:
    """Match packs and deterministically merge their abstract requirements."""
    facts = _project_facts(blueprint, repository)
    applicable = {pack.pack_id: pack for pack in packs if matches(pack.match, facts)}
    selected = _apply_pack_conflicts(applicable)
    contributions: dict[str, list[_Contribution]] = {}
    for pack_id in sorted(selected):
        pack = selected[pack_id]
        suppressed = {
            requirement_id
            for exception in pack.exceptions
            if matches(exception.when, facts)
            for requirement_id in exception.suppress_requirements
        }
        for requirement in pack.requirements:
            if requirement.requirement_id in suppressed:
                continue
            contributions.setdefault(requirement.capability, []).append(
                _Contribution(
                    pack_id=pack.pack_id,
                    requirement_id=requirement.requirement_id,
                    capability=requirement.capability,
                    strength=requirement.strength,
                    rationale=requirement.rationale,
                    verification=requirement.verification,
                )
            )
    override_map = _normalize_overrides(overrides)
    override_map = _normalize_overrides(overrides)
    merged: list[AbstractCapabilityRequirement] = []
    for capability in sorted(contributions):
        merged_requirement = _merge_requirement(
            capability, contributions[capability], override_map.get(capability)
        )
        if merged_requirement is not None:
            merged.append(merged_requirement)
    return tuple(merged)



def _project_facts(blueprint: Blueprint, repository: RepositorySnapshot) -> dict[str, object]:
    facts: dict[str, object] = {
        "project_name": blueprint.project_name,
        "goal": blueprint.goal,
        "lifecycle_stage": blueprint.lifecycle_stage.value,
        "risk_level": blueprint.risk_level.value,
        "target_platforms": blueprint.target_platforms,
        **blueprint.preferences,
    }
    facts.update({constraint.name: constraint.value for constraint in blueprint.constraints})
    for item in repository.facts:
        if item.value is not None:
            facts.setdefault(item.key, item.value)
    return facts


def _apply_pack_conflicts(applicable: dict[str, PracticePack]) -> dict[str, PracticePack]:
    selected = dict(applicable)
    directives: list[tuple[str, str, ConflictResolution, str]] = []
    for pack_id in sorted(applicable):
        for conflict in applicable[pack_id].conflicts:
            if conflict.pack_id in applicable:
                directives.append(
                    (pack_id, conflict.pack_id, conflict.resolution, conflict.rationale)
                )
    for source, target, resolution, rationale in directives:
        if source not in selected or target not in selected:
            continue
        if resolution is ConflictResolution.ERROR:
            raise PracticeConflictError(
                f"Practice Packs {source!r} and {target!r} conflict: {rationale}. "
                "Disable one pack or add an explicit conflict policy."
            )
        if resolution is ConflictResolution.PREFER_SELF:
            selected.pop(target, None)
        else:
            selected.pop(source, None)
    return selected


def _normalize_overrides(
    overrides: Iterable[RequirementOverride],
) -> dict[str, RequirementOverride]:
    normalized: dict[str, RequirementOverride] = {}
    for override in overrides:
        if override.capability in normalized:
            raise ValueError(f"duplicate requirement override: {override.capability}")
        normalized[override.capability] = override
    return normalized


def _merge_requirement(
    capability: str,
    contributions: list[_Contribution],
    override: RequirementOverride | None,
) -> AbstractCapabilityRequirement | None:
    if override is not None and not override.enabled:
        return None
    ordered = sorted(contributions, key=lambda item: (item.pack_id, item.requirement_id))
    default_strength = max(ordered, key=lambda item: _STRENGTH_RANK[item.strength]).strength
    strength = override.strength if override and override.strength else default_strength
    return AbstractCapabilityRequirement(
        capability=capability,
        strength=strength,
        originating_packs=tuple(item.pack_id for item in ordered),
        originating_requirements=tuple(item.requirement_id for item in ordered),
        reasons=tuple(item.rationale for item in ordered),
        verification=tuple(step for item in ordered for step in item.verification),
        overridden=override is not None,
    )
