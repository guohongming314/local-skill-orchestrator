from vibe.recommendation import ContextValue, browser_value, codegraph_value, memory_value


def test_medium_complex_repository_recommends_codegraph() -> None:
    value = codegraph_value(
        {
            "repository_size": "medium",
            "module_count": 24,
            "language_count": "3",
            "cross_module_changes": "frequent",
            "local_symbol_index": False,
        }
    )

    assert value.recommended is True
    assert value.score > 0
    assert any("cross-module" in reason for reason in value.reasons)


def test_large_simple_repository_defers_codegraph() -> None:
    value = codegraph_value(
        {
            "repository_size": "large",
            "module_count": 4,
            "language_count": 1,
            "cross_module_changes": "rare",
            "local_symbol_index": True,
        }
    )

    assert value.recommended is False
    assert any("local symbol index" in reason for reason in value.reasons)


def test_detected_large_monorepo_preserves_codegraph_recommendation() -> None:
    value = codegraph_value(
        {
            "repository_size": "large",
            "is_monorepo": "true",
        }
    )

    assert value.recommended is True
    assert "monorepo" in " ".join(value.reasons).casefold()


def test_codegraph_handles_missing_and_malformed_numeric_facts() -> None:
    assert codegraph_value({}) == ContextValue(False, 0, ())
    value = codegraph_value({"module_count": None, "language_count": "many"})
    assert value.recommended is False
    assert isinstance(value.score, int)


def test_memory_denial_is_a_strong_negative() -> None:
    value = memory_value({"memory.persistence": "denied", "lifecycle_stage": "production"})

    assert value.recommended is False
    assert value.score <= -10
    assert any("denied" in reason for reason in value.reasons)


def test_memory_is_not_recommended_for_exploration() -> None:
    value = memory_value({"memory.persistence": "allowed", "lifecycle_stage": "exploration"})

    assert value.recommended is False
    assert any("exploration" in reason for reason in value.reasons)


def test_long_lived_project_with_explicit_preference_recommends_memory() -> None:
    value = memory_value({"memory.persistence": True, "lifecycle_stage": "maintenance"})

    assert value.recommended is True
    assert any("durable decisions" in reason for reason in value.reasons)


def test_browser_value_only_promotes_interactive_control_when_explicitly_allowed() -> None:
    unknown = browser_value({})
    allowed = browser_value({"browser.interactive-debugging": True})

    assert unknown.recommended is False
    assert "unknown" in unknown.reasons[0]
    assert allowed.recommended is True
    assert allowed.score > unknown.score
    assert "interactive browser" in allowed.reasons[0]
