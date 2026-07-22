from vibe.recommendation.questions import RecommendationQuestionContext, adaptive_questions


def context(
    *,
    requirements: tuple[str, ...] = (),
    local_capabilities: tuple[str, ...] = (),
    repository_facts: dict[str, object] | None = None,
    unknown_decisions: frozenset[str] = frozenset(),
) -> RecommendationQuestionContext:
    return RecommendationQuestionContext(
        requirements=requirements,
        local_capabilities=local_capabilities,
        repository_facts=repository_facts or {},
        unknown_decisions=unknown_decisions,
    )


def test_browser_debugging_question_is_asked_only_when_it_can_change_candidates() -> None:
    questions = adaptive_questions(
        context(
            requirements=("browser.validation",),
            local_capabilities=("cli.playwright",),
            unknown_decisions=frozenset({"browser.interactive-debugging"}),
        )
    )

    assert [question.question_id for question in questions] == [
        "browser.interactive-debugging"
    ]
    assert "Chrome DevTools" not in questions[0].text
    assert "interactive browser-control candidates" in questions[0].impact
    assert "existing runner remains preferred" in questions[0].impact


def test_memory_persistence_question_is_asked_outside_exploration() -> None:
    questions = adaptive_questions(
        context(
            requirements=("project.continuity-memory",),
            repository_facts={"project.lifecycle": "existing"},
            unknown_decisions=frozenset({"memory.persistence"}),
        )
    )

    assert [question.question_id for question in questions] == ["memory.persistence"]
    assert "persistent candidates" in questions[0].impact
    assert "storage boundary" in questions[0].impact


def test_memory_persistence_question_is_omitted_during_exploration() -> None:
    questions = adaptive_questions(
        context(
            requirements=("project.continuity-memory",),
            repository_facts={"project.lifecycle": "exploration"},
            unknown_decisions=frozenset({"memory.persistence"}),
        )
    )

    assert questions == ()


def test_known_decisions_and_irrelevant_conditions_are_not_asked() -> None:
    questions = adaptive_questions(
        context(
            requirements=("browser.validation", "project.continuity-memory"),
            local_capabilities=("cli.playwright",),
            repository_facts={"project.lifecycle": "existing"},
            unknown_decisions=frozenset(),
        )
    )

    assert questions == ()


def test_adaptive_question_order_is_stable() -> None:
    selection_context = context(
        requirements=("project.continuity-memory", "browser.validation"),
        local_capabilities=("cli.playwright",),
        repository_facts={"project.lifecycle": "existing"},
        unknown_decisions=frozenset(
            {"memory.persistence", "browser.interactive-debugging"}
        ),
    )

    first = adaptive_questions(selection_context)
    second = adaptive_questions(selection_context)

    assert first == second
    assert [question.question_id for question in first] == [
        "browser.interactive-debugging",
        "memory.persistence",
    ]
