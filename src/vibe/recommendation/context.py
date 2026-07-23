"""Deterministic contextual value evaluation for conditional capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextValue:
    recommended: bool
    score: int
    reasons: tuple[str, ...]


def codegraph_value(facts: Mapping[str, object]) -> ContextValue:
    """Evaluate whether repository complexity makes graph navigation worthwhile."""
    score = 0
    reasons: list[str] = []
    module_count = _safe_int(facts.get("module_count"))
    language_count = _safe_int(facts.get("language_count"))

    if _normalized(facts.get("repository_size")) == "large" and _is_true(facts.get("is_monorepo")):
        score += 6
        reasons.append("a large monorepo increases cross-module navigation value")
    if module_count is not None and module_count >= 20:
        score += 3
        reasons.append(f"{module_count} modules increase relationship-analysis value")
    if language_count is not None and language_count >= 2:
        score += 2
        reasons.append(f"{language_count} languages increase navigation complexity")
    if _normalized(facts.get("cross_module_changes")) == "frequent":
        score += 4
        reasons.append("frequent cross-module changes strongly favor graph navigation")
    if _is_true(facts.get("local_symbol_index")):
        score -= 5
        reasons.append("an existing local symbol index lowers incremental value")
    if module_count is not None and module_count < 5:
        score -= 2
        reasons.append("few modules reduce relationship-analysis value")
    if language_count == 1:
        score -= 1
        reasons.append("a single language reduces navigation complexity")
    if _normalized(facts.get("cross_module_changes")) == "rare":
        score -= 1
        reasons.append("rare cross-module changes reduce impact-analysis value")

    return ContextValue(score >= 6, score, tuple(reasons))


def memory_value(facts: Mapping[str, object]) -> ContextValue:
    """Evaluate persistent-memory value without treating missing consent as permission."""
    preference = facts.get("memory.persistence")
    normalized_preference = _normalized(preference)
    lifecycle = _normalized(facts.get("lifecycle_stage"))

    if normalized_preference in {"denied", "deny", "false", "no"} or preference is False:
        return ContextValue(False, -20, ("persistent memory was explicitly denied",))
    if lifecycle == "exploration":
        return ContextValue(
            False,
            -8,
            ("persistent memory adds little value during short-lived exploration",),
        )
    if (
        normalized_preference in {"allowed", "allow", "true", "yes"} or preference is True
    ) and lifecycle in {"active-development", "maintenance", "production"}:
        return ContextValue(
            True,
            6,
            ("persistent context preserves durable decisions across work sessions",),
        )
    return ContextValue(
        False,
        0,
        ("persistent memory requires an explicit persistence preference",),
    )


def browser_value(facts: Mapping[str, object]) -> ContextValue:
    """Evaluate the incremental value of interactive browser control."""
    preference = facts.get("browser.interactive-debugging")
    normalized = _normalized(preference)
    if preference is True or normalized in {"true", "yes", "allowed", "allow"}:
        return ContextValue(
            True,
            10,
            ("explicit interactive browser debugging preference favors browser control",),
        )
    if preference is False or normalized in {"false", "no", "denied", "deny"}:
        return ContextValue(
            False,
            -2,
            ("interactive browser debugging was explicitly declined",),
        )
    return ContextValue(
        False,
        0,
        ("interactive browser preference unknown; available provider retained",),
    )


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _normalized(value: object) -> str:
    return str(value).strip().casefold() if value is not None else ""


def _is_true(value: object) -> bool:
    return value is True or _normalized(value) in {"true", "yes", "1"}
