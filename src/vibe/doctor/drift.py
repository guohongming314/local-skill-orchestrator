"""Deterministic classification of repository and generated-file drift."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vibe.compiler.invalidation import InvalidationKind, InvalidationReason
from vibe.materialize.changeset import ChangeKind, ChangeSet
from vibe.materialize.ownership import FileOwnership
from vibe.models.repository import RepositoryFact, RepositorySnapshot

_LOCKFILE = ".ai-project/capabilities.lock"


class DriftClassification(StrEnum):
    EXPECTED = "expected"
    BENIGN = "benign"
    ACTIONABLE = "actionable"
    BLOCKING = "blocking"
    SECURITY = "security"


@dataclass(frozen=True)
class DriftReport:
    reasons: tuple[InvalidationReason, ...]

    @property
    def invalidates_configuration(self) -> bool:
        return any(reason.invalidates_configuration for reason in self.reasons)


def detect_drift(
    baseline: RepositorySnapshot,
    current: RepositorySnapshot,
    changeset: ChangeSet,
) -> DriftReport:
    """Compare known project facts and regenerated managed files without writing."""
    reasons: list[InvalidationReason] = []
    if baseline.head != current.head:
        reasons.append(
            InvalidationReason(
                kind=InvalidationKind.GIT_HEAD_CHANGED,
                sources=("git HEAD",),
                invalidates_configuration=False,
                expected_digest=baseline.head,
                actual_digest=current.head,
            )
        )

    baseline_stack = _stack_facts(baseline.facts)
    current_stack = _stack_facts(current.facts)
    if baseline_stack != current_stack:
        reasons.append(
            InvalidationReason(
                kind=InvalidationKind.TECHNOLOGY_STACK_CHANGED,
                sources=_changed_stack_sources(baseline_stack, current_stack),
                invalidates_configuration=True,
            )
        )

    if baseline.source_digest != current.source_digest:
        reasons.append(
            InvalidationReason(
                kind=InvalidationKind.REPOSITORY_SOURCE_CHANGED,
                sources=("repository source files",),
                invalidates_configuration=False,
                expected_digest=baseline.source_digest,
                actual_digest=current.source_digest,
            )
        )

    for operation in changeset.operations:
        if operation.kind is ChangeKind.UNCHANGED:
            continue
        if operation.ownership is FileOwnership.OBSERVED:
            continue
        kind = (
            InvalidationKind.LOCKFILE_CHANGED
            if operation.path == _LOCKFILE
            else InvalidationKind.MANAGED_FILE_CHANGED
        )
        reasons.append(
            InvalidationReason(
                kind=kind,
                sources=(operation.path,),
                invalidates_configuration=True,
                expected_digest=operation.after_digest,
                actual_digest=operation.before_digest,
            )
        )

    return DriftReport(tuple(sorted(reasons, key=_reason_key)))


def _stack_facts(facts: tuple[RepositoryFact, ...]) -> dict[str, RepositoryFact]:
    return {fact.key: fact for fact in facts if fact.key.startswith("stack.")}


def _changed_stack_sources(
    baseline: dict[str, RepositoryFact],
    current: dict[str, RepositoryFact],
) -> tuple[str, ...]:
    sources: set[str] = set()
    for key in baseline.keys() | current.keys():
        before = baseline.get(key)
        after = current.get(key)
        if before == after:
            continue
        if before is not None:
            sources.update(before.sources)
        if after is not None:
            sources.update(after.sources)
    return tuple(sorted(sources)) or ("technology stack facts",)


def _reason_key(reason: InvalidationReason) -> tuple[str, tuple[str, ...]]:
    return reason.kind.value, reason.sources
