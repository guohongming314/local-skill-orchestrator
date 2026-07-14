"""Compile the minimum deterministic context needed for one task phase."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from vibe.compiler.intent import TaskIntent
from vibe.models.capability import Permission
from vibe.models.capsule import ContextCapsule, SourceReference
from vibe.models.task import TaskPlan


class SourceKind(StrEnum):
    REPOSITORY = "repository"
    CONFIGURATION = "configuration"
    MEMORY = "memory"


@dataclass(frozen=True)
class CapabilityCandidate:
    capability_id: str
    provides: tuple[str, ...]
    phases: tuple[str, ...]
    permissions: frozenset[Permission] = frozenset()


@dataclass(frozen=True)
class ContextSource:
    source_id: str
    digest: str
    kind: SourceKind


_CODE_RELATIONSHIP_ANALYSIS = "code-relationship-analysis"
_DEFAULT_TOKEN_BUDGET = 4096


def compile_context_capsule(
    intent: TaskIntent,
    plan: TaskPlan,
    *,
    phase: str,
    candidates: tuple[CapabilityCandidate, ...],
    sources: tuple[ContextSource, ...],
    head: str,
    user_scope_digest: str,
    token_budget: int = _DEFAULT_TOKEN_BUDGET,
) -> ContextCapsule:
    """Compile context only; this function never executes task capabilities."""
    if intent.task_id != plan.task_id:
        raise ValueError("intent and plan task_id values must match")
    phases = {item.phase_id: item for item in plan.phases}
    if phase not in phases:
        raise ValueError(f"phase {phase!r} is not present in the task plan")
    if not sources:
        raise ValueError("at least one context source is required")

    selected = set(phases[phase].capability_ids)
    if phase == "inspect" and intent.cross_module:
        selected.update(
            candidate.capability_id
            for candidate in candidates
            if phase in candidate.phases
            and _CODE_RELATIONSHIP_ANALYSIS in candidate.provides
        )

    candidate_ids = {candidate.capability_id for candidate in candidates}
    rejected = candidate_ids - selected
    permissions = frozenset(
        permission
        for candidate in candidates
        if candidate.capability_id in selected
        for permission in candidate.permissions
    )
    constraints = tuple(
        f"Treat {source.source_id} as a lead; verify it against repository sources."
        for source in sorted(sources, key=lambda item: item.source_id)
        if source.kind is SourceKind.MEMORY
    )
    scope_digest = _scope_digest(intent.scope)

    return ContextCapsule(
        task_id=intent.task_id,
        intent=intent.summary,
        scope=intent.scope,
        constraints=constraints,
        acceptance_criteria=intent.acceptance_criteria,
        current_phase=phase,
        selected_capability_ids=tuple(sorted(selected)),
        requested_permissions=tuple(sorted(permissions, key=lambda item: item.value)),
        rejected_capability_ids=tuple(sorted(rejected)),
        sources=tuple(
            SourceReference(source_id=source.source_id, digest=source.digest)
            for source in sorted(sources, key=lambda item: item.source_id)
        ),
        invalidation_conditions=(
            f"git-head:{head}",
            f"user-scope:{user_scope_digest}",
            f"phase:{phase}",
            f"scope:{scope_digest}",
        ),
        token_budget=token_budget,
    )


def capsule_is_valid(
    capsule: ContextCapsule,
    *,
    head: str,
    user_scope_digest: str,
    phase: str,
    scope: tuple[str, ...],
) -> bool:
    """Return whether the inputs that determine a capsule are unchanged."""
    normalized_scope = tuple(
        sorted({item.strip().replace("\\", "/") for item in scope if item.strip()})
    )
    expected = (
        f"git-head:{head}",
        f"user-scope:{user_scope_digest}",
        f"phase:{phase}",
        f"scope:{_scope_digest(normalized_scope)}",
    )
    return capsule.invalidation_conditions == expected


def _scope_digest(scope: tuple[str, ...]) -> str:
    payload = "\0".join(scope).encode()
    return sha256(payload).hexdigest()
