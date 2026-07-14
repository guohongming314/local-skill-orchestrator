from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from vibe.codex.exec_fallback import CodexExecFallback, StructuredResultError
from vibe.conversation.interview import InterviewInput, InterviewQuestion, build_interview
from vibe.conversation.runner import ConversationRunner
from vibe.models.repository import (
    FactConfidence,
    RepositoryFact,
    RepositorySnapshot,
)

FAKE_SERVER = Path(__file__).parents[1] / "fakes" / "fake_interview_app_server.py"
FAKE_EXEC = Path(__file__).parents[1] / "fakes" / "fake_codex_exec.py"


def snapshot(root: Path) -> RepositorySnapshot:
    return RepositorySnapshot(
        root=root,
        source_digest="0123456789abcdef",
        is_empty=False,
    )


def app_command(mode: str, state: Path) -> tuple[str, ...]:
    return (sys.executable, str(FAKE_SERVER), mode, str(state))


def fallback(mode: str, invocation: Path) -> CodexExecFallback:
    return CodexExecFallback((sys.executable, str(FAKE_EXEC), mode, str(invocation)))


@pytest.mark.anyio
async def test_scripted_conversation_returns_schema_valid_project_result(
    tmp_path: Path,
) -> None:
    repository = snapshot(tmp_path)
    interview = build_interview(
        InterviewInput(repository=repository, unknowns=("project.goal", "risk.tolerance"))
    )
    answers = iter(("Ship a safe service", "medium"))
    state = tmp_path / "server.json"
    runner = ConversationRunner(
        app_server_command=app_command("valid", state),
        exec_fallback=fallback("fail-if-called", tmp_path / "exec.json"),
    )

    result = await runner.run(
        repository=repository,
        interview=interview,
        ask_user=lambda _question: next(answers),
    )

    assert result.blueprint.goal == "Ship a safe service"
    assert result.field_sources["goal"].value == "confirmed"
    recorded = json.loads(state.read_text(encoding="utf-8"))
    assert recorded["turn_count"] == 4
    assert recorded["approval_responses"] == [
        {"id": "approval-1", "result": {"decision": "decline"}}
    ]


@pytest.mark.anyio
async def test_malformed_app_output_uses_exec_fallback_once_then_fails_cleanly(
    tmp_path: Path,
) -> None:
    repository = snapshot(tmp_path)
    interview = build_interview(InterviewInput(repository=repository))
    invocation = tmp_path / "exec.json"
    runner = ConversationRunner(
        app_server_command=app_command("invalid", tmp_path / "server.json"),
        exec_fallback=fallback("invalid", invocation),
    )

    with pytest.raises(StructuredResultError, match="fallback output"):
        await runner.run(
            repository=repository,
            interview=interview,
            ask_user=lambda _question: "unused",
        )

    assert invocation.exists()


@pytest.mark.anyio
async def test_revision_updates_final_result_and_reasks_stale_dependents(
    tmp_path: Path,
) -> None:
    repository = snapshot(tmp_path)
    interview = build_interview(
        InterviewInput(repository=repository, unknowns=("project.goal", "risk.tolerance"))
    )
    responses = iter(
        (
            "Ship the first service",
            "revise project.goal",
            "Ship the revised service",
            "high",
        )
    )
    asked: list[str] = []
    runner = ConversationRunner(
        app_server_command=app_command("valid", tmp_path / "server.json"),
        exec_fallback=fallback("fail-if-called", tmp_path / "exec.json"),
    )

    def ask(question: InterviewQuestion) -> str:
        asked.append(question.question_id)
        return next(responses)

    result = await runner.run(
        repository=repository,
        interview=interview,
        ask_user=ask,
    )

    assert asked == [
        "project.goal",
        "risk.tolerance",
        "project.goal",
        "risk.tolerance",
    ]
    assert result.blueprint.goal == "Ship the revised service"
    assert result.blueprint.risk_level.value == "high"


@pytest.mark.anyio
async def test_locked_answer_survives_contradicting_final_model_turn(tmp_path: Path) -> None:
    repository = snapshot(tmp_path)
    interview = build_interview(
        InterviewInput(repository=repository, unknowns=("project.goal", "risk.tolerance"))
    )
    responses = iter(("Keep this exact goal", "lock project.goal", "medium"))
    runner = ConversationRunner(
        app_server_command=app_command("valid", tmp_path / "server.json"),
        exec_fallback=fallback("fail-if-called", tmp_path / "exec.json"),
    )

    result = await runner.run(
        repository=repository,
        interview=interview,
        ask_user=lambda _question: next(responses),
    )

    assert result.blueprint.goal == "Keep this exact goal"
    assert result.locked_decisions == frozenset({"goal"})


@pytest.mark.anyio
async def test_accepting_recommended_default_records_confirmed_provenance(
    tmp_path: Path,
) -> None:
    repository = RepositorySnapshot(
        root=tmp_path,
        source_digest="0123456789abcdef",
        is_empty=False,
        facts=(
            RepositoryFact(
                key="project.goal",
                value="Ship the repository-backed default",
                confidence=FactConfidence.INFERRED,
                sources=("README.md",),
            ),
        ),
    )
    interview = build_interview(
        InterviewInput(repository=repository, unknowns=("project.goal",))
    )
    question = interview.questions[0]
    runner = ConversationRunner(
        app_server_command=app_command("valid", tmp_path / "server.json"),
        exec_fallback=fallback("fail-if-called", tmp_path / "exec.json"),
    )

    result = await runner.run(
        repository=repository,
        interview=interview,
        ask_user=lambda _question: "accept",
    )

    assert question.recommended_default == "Ship the repository-backed default"
    assert question.recommendation_reason is not None
    assert "README.md" in question.recommendation_reason
    assert result.blueprint.goal == "Ship the repository-backed default"
    assert result.field_sources["goal"].value == "confirmed"
    assert result.field_provenance["goal"].value == "recommended-default"
