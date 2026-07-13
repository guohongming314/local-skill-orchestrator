from __future__ import annotations

from collections.abc import Mapping

from vibe.practices.models import MatchCondition, MatchOperator, MatchRule


def matches(rule: MatchRule, facts: Mapping[str, object]) -> bool:
    """Evaluate a declarative match rule against normalized project facts."""
    return (
        all(_condition_matches(condition, facts) for condition in rule.all_of)
        and (not rule.any_of or any(_condition_matches(item, facts) for item in rule.any_of))
        and not any(_condition_matches(condition, facts) for condition in rule.none_of)
    )


def _condition_matches(condition: MatchCondition, facts: Mapping[str, object]) -> bool:
    present = condition.field in facts and facts[condition.field] is not None
    actual = facts.get(condition.field)
    expected = condition.value
    if condition.operator is MatchOperator.EXISTS:
        return present is bool(expected)
    if not present:
        return False
    if condition.operator is MatchOperator.EQUALS:
        return actual == expected
    if condition.operator is MatchOperator.CONTAINS:
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, (list, tuple, set, frozenset)):
            return expected in actual
        return False
    if condition.operator is MatchOperator.IN:
        return isinstance(expected, tuple) and actual in expected
    return False
