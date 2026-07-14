from pathlib import Path

from vibe.conversation.interview import InterviewInput, InterviewResult, build_interview
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot


def snapshot(*, empty: bool, facts: tuple[RepositoryFact, ...] = ()) -> RepositorySnapshot:
    return RepositorySnapshot(
        root=Path("project"),
        is_empty=empty,
        facts=facts,
        source_digest="a" * 64,
    )


def ids(result: InterviewResult) -> list[str]:
    return [question.question_id for question in result.questions]


def test_confirmed_repository_facts_are_not_reasked() -> None:
    result = build_interview(
        InterviewInput(
            repository=snapshot(
                empty=False,
                facts=(
                    RepositoryFact(
                        key="project.goal",
                        value="Ship the existing API",
                        confidence=FactConfidence.CONFIRMED,
                        sources=("README.md",),
                    ),
                    RepositoryFact(
                        key="project.lifecycle",
                        value="existing",
                        confidence=FactConfidence.CONFIRMED,
                        sources=("repository scan",),
                    ),
                ),
            ),
            unknowns=("risk.tolerance",),
        )
    )

    assert "project.goal" not in ids(result)
    assert "project.lifecycle" not in ids(result)
    assert ids(result) == ["risk.tolerance"]


def test_empty_and_existing_projects_receive_different_initial_questions() -> None:
    blank = build_interview(
        InterviewInput(
            repository=snapshot(empty=True),
            unknowns=("project.goal", "project.lifecycle"),
        )
    )
    existing = build_interview(
        InterviewInput(
            repository=snapshot(empty=False),
            unknowns=("project.goal", "project.lifecycle"),
        )
    )

    assert blank.questions[0].question_id == "project.goal"
    assert "create" in blank.questions[0].text.lower()
    assert existing.questions[0].question_id == "project.goal"
    assert "change" in existing.questions[0].text.lower()
    assert blank.questions[0].text != existing.questions[0].text


def test_high_risk_conflict_requires_explicit_confirmation() -> None:
    result = build_interview(
        InterviewInput(
            repository=snapshot(
                empty=False,
                facts=(
                    RepositoryFact(
                        key="permissions.write_project",
                        value=["required", "prohibited"],
                        confidence=FactConfidence.CONFLICT,
                        sources=("policy", "request"),
                    ),
                ),
            ),
            conflicts=("permissions.write_project",),
        )
    )

    question = result.questions[0]
    assert question.question_id == "permissions.write_project"
    assert question.requires_explicit_confirmation is True
    assert "confirm" in question.text.lower()


def test_questions_cover_only_unknown_high_impact_dimensions() -> None:
    result = build_interview(
        InterviewInput(
            repository=snapshot(empty=False),
            unknowns=(
                "constraints.deadline",
                "preferences.testing",
                "low_impact.editor_theme",
            ),
            inventory_summary=("codegraph", "pytest", "memory-plugin"),
            preferences={"preferences.testing": "test-first"},
        )
    )

    assert ids(result) == ["constraints.deadline"]
    rendered = " ".join(question.text.lower() for question in result.questions)
    assert "codegraph" not in rendered
    assert "pytest" not in rendered
    assert "memory-plugin" not in rendered


def test_question_order_is_stable_and_tool_names_are_not_exposed() -> None:
    interview_input = InterviewInput(
        repository=snapshot(empty=False),
        unknowns=(
            "preferences.workflow",
            "permissions.network",
            "project.goal",
            "risk.tolerance",
            "constraints.deadline",
        ),
        inventory_summary=("secret-tool-name",),
    )

    first = build_interview(interview_input)
    second = build_interview(interview_input)
    assert first == second
    assert ids(first) == [
        "project.goal",
        "risk.tolerance",
        "constraints.deadline",
        "permissions.network",
        "preferences.workflow",
    ]
    assert "secret-tool-name" not in " ".join(q.text for q in first.questions)


def test_blank_repository_always_asks_for_project_type() -> None:
    result = build_interview(
        InterviewInput(
            repository=snapshot(empty=True),
            unknowns=("project.goal",),
        )
    )

    assert "project.type" in ids(result)


def test_inferred_project_type_is_not_reasked() -> None:
    result = build_interview(
        InterviewInput(
            repository=snapshot(
                empty=False,
                facts=(
                    RepositoryFact(
                        key="project_type",
                        value="web-application",
                        confidence=FactConfidence.INFERRED,
                        sources=("package.json",),
                    ),
                ),
            ),
        )
    )

    assert "project.type" not in ids(result)


def test_conflicting_project_type_is_reasked() -> None:
    result = build_interview(
        InterviewInput(
            repository=snapshot(
                empty=False,
                facts=(
                    RepositoryFact(
                        key="project_type",
                        value=["backend-api", "web-application"],
                        confidence=FactConfidence.CONFLICT,
                        sources=("package.json", "pyproject.toml"),
                    ),
                ),
            ),
        )
    )

    assert "project.type" in ids(result)
