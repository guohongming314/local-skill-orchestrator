from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from vibe.codex.exec_fallback import CodexExecFallback, StructuredResultError
from vibe.conversation.interview import (
    InterviewInput,
    InterviewQuestion,
    InterviewResult,
    build_interview,
)
from vibe.conversation.runner import ConversationRunner, _context_prompt, _reconcile_answers
from vibe.conversation.structured_result import (
    FieldProvenance,
    StructuredProjectResult,
    ValueSource,
)
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.decisions import (
    AuthorizationState,
    DecisionSource,
    NetworkDecision,
    NetworkPolicy,
    PermissionDecision,
    ProjectDecisions,
    TriState,
)
from vibe.models.repository import (
    FactConfidence,
    RepositoryFact,
    RepositorySnapshot,
)
from vibe.models.risk import RiskLevel

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


def model_result(root: Path) -> StructuredProjectResult:
    return StructuredProjectResult(
        blueprint=Blueprint(
            project_name="fixture",
            goal="model goal",
            lifecycle_stage=LifecycleStage.EXPLORATION,
            risk_level=RiskLevel.LOW,
            repository_digest="0123456789abcdef",
        ),
        field_sources={
            "project_name": ValueSource.INFERRED,
            "goal": ValueSource.INFERRED,
            "lifecycle_stage": ValueSource.INFERRED,
            "risk_level": ValueSource.INFERRED,
            "repository_digest": ValueSource.INFERRED,
        },
    )


def test_context_prompt_serializes_question_impact(tmp_path: Path) -> None:
    prompt = _context_prompt(
        snapshot(tmp_path),
        InterviewResult(
            questions=(
                InterviewQuestion(
                    question_id="memory.persistence",
                    category="recommendation",
                    text="Should memory persist?",
                    impact="Changes persistent candidates and their storage boundary.",
                ),
            ),
            confirmed_fact_keys=(),
            unresolved_keys=("memory.persistence",),
        ),
    )

    question = json.loads(prompt)["questions"][0]
    assert question["impact"] == "Changes persistent candidates and their storage boundary."


def test_context_prompt_preserves_ordinary_question_payload_shape(tmp_path: Path) -> None:
    prompt = _context_prompt(
        snapshot(tmp_path),
        InterviewResult(
            questions=(
                InterviewQuestion(
                    question_id="risk.tolerance",
                    category="risk",
                    text="What is the risk tolerance?",
                ),
            ),
            confirmed_fact_keys=(),
            unresolved_keys=("risk.tolerance",),
        ),
    )

    question = json.loads(prompt)["questions"][0]
    assert set(question) == {
        "id",
        "text",
        "category",
        "requires_explicit_confirmation",
        "recommended_default",
        "recommendation_reason",
    }
    assert "impact" not in question


@pytest.mark.parametrize(
    ("question_id", "answer", "expected"),
    (
        ("permissions.write_project", "yes, you may change project files", TriState.ALLOWED),
        ("permissions.write_project", "allowed", TriState.ALLOWED),
        ("permissions.write_project", "do not modify files", TriState.DENIED),
        ("permissions.execute_command", "you may execute commands", TriState.ALLOWED),
        ("permissions.execute_command", "可以执行本地验证命令", TriState.ALLOWED),
        ("permissions.execute_command", "不允许执行命令", TriState.DENIED),
        ("permissions.execute_command", "禁止", TriState.DENIED),
        ("permissions.execute_command", "这不是可以直接执行的事情", TriState.UNKNOWN),
        ("permissions.execute_command", "不太可以执行命令", TriState.UNKNOWN),
        ("permissions.execute_command", "是不是可以执行命令", TriState.UNKNOWN),
        ("permissions.execute_command", "notable commands may help", TriState.UNKNOWN),
    ),
)
def test_reconcile_maps_permission_answers_conservatively(
    tmp_path: Path, question_id: str, answer: str, expected: TriState
) -> None:
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: answer},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    decision = getattr(reconciled.blueprint.decisions, question_id.removeprefix("permissions."))
    assert decision.value is expected
    assert decision.provenance.source is DecisionSource.USER_RESPONSE
    assert decision.provenance.reference == question_id


@pytest.mark.parametrize(
    "question_id",
    (
        "permissions.write_project",
        "permissions.execute_command",
        "permissions.network",
    ),
)
@pytest.mark.parametrize(
    "answer",
    ("maybe yes", "possibly allowed", "you may, if I approve later"),
)
def test_reconcile_rejects_ambiguous_english_permission_answers(
    tmp_path: Path, question_id: str, answer: str
) -> None:
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: answer},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    field = question_id.removeprefix("permissions.")
    if field == "network":
        assert reconciled.blueprint.decisions.network_policy.value is NetworkPolicy.UNKNOWN
    else:
        assert getattr(reconciled.blueprint.decisions, field).value is TriState.UNKNOWN


@pytest.mark.parametrize(
    "question_id",
    (
        "permissions.write_project",
        "permissions.execute_command",
        "permissions.network",
    ),
)
def test_reconcile_prioritizes_explicit_english_denial(
    tmp_path: Path, question_id: str
) -> None:
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: "you may not do that"},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    field = question_id.removeprefix("permissions.")
    if field == "network":
        assert reconciled.blueprint.decisions.network_policy.value is NetworkPolicy.DENIED
    else:
        assert getattr(reconciled.blueprint.decisions, field).value is TriState.DENIED


@pytest.mark.parametrize(
    ("answer", "expected"),
    (
        ("maybe read-only network access", NetworkPolicy.UNKNOWN),
        ("read-only if I approve later", NetworkPolicy.UNKNOWN),
        ("possibly read-only", NetworkPolicy.UNKNOWN),
        ("可能只读", NetworkPolicy.UNKNOWN),
        ("只读,如果之后批准", NetworkPolicy.UNKNOWN),
        ("read-only network access", NetworkPolicy.ALLOWED_READONLY),
        ("you may not use the network", NetworkPolicy.DENIED),
    ),
)
def test_reconcile_classifies_network_uncertainty_before_readonly(
    tmp_path: Path, answer: str, expected: NetworkPolicy
) -> None:
    question_id = "permissions.network"
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: answer},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    assert reconciled.blueprint.decisions.network_policy.value is expected


@pytest.mark.parametrize(
    "question_id",
    (
        "permissions.write_project",
        "permissions.execute_command",
        "permissions.network",
    ),
)
@pytest.mark.parametrize("answer", ("not approved", "not approve", "not permit"))
def test_reconcile_never_grants_negated_english_affirmations(
    tmp_path: Path, question_id: str, answer: str
) -> None:
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: answer},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    field = question_id.removeprefix("permissions.")
    if field == "network":
        assert reconciled.blueprint.decisions.network_policy.value is not NetworkPolicy.ALLOWED
        assert (
            reconciled.blueprint.decisions.network_policy.value
            is not NetworkPolicy.ALLOWED_READONLY
        )
    else:
        assert getattr(reconciled.blueprint.decisions, field).value is not TriState.ALLOWED


@pytest.mark.parametrize(
    "answer",
    (
        "not read-only",
        "read-only is unavailable",
        "不是只读",
        "只读不可用",
        "只读不行",
        "只读不支持",
        "不允许只读",
    ),
)
def test_reconcile_never_grants_negated_or_unavailable_readonly(
    tmp_path: Path, answer: str
) -> None:
    question_id = "permissions.network"
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: answer},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    assert (
        reconciled.blueprint.decisions.network_policy.value
        is not NetworkPolicy.ALLOWED_READONLY
    )


@pytest.mark.parametrize(
    ("question_id", "answer", "expected"),
    (
        ("permissions.execute_command", "可以不执行命令", TriState.DENIED),
        ("permissions.write_project", "允许不修改项目文件", TriState.DENIED),
        ("permissions.execute_command", "可以禁止执行命令", TriState.DENIED),
        ("permissions.write_project", "允许修改项目文件", TriState.ALLOWED),
        ("permissions.execute_command", "可以执行命令", TriState.ALLOWED),
    ),
)
def test_reconcile_requires_complete_chinese_permission_phrases(
    tmp_path: Path, question_id: str, answer: str, expected: TriState
) -> None:
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: answer},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    field = question_id.removeprefix("permissions.")
    assert getattr(reconciled.blueprint.decisions, field).value is expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    (
        ("只读也不允许", NetworkPolicy.DENIED),
        ("只读网络访问禁止", NetworkPolicy.DENIED),
        ("只读网络访问", NetworkPolicy.ALLOWED_READONLY),
    ),
)
def test_reconcile_requires_complete_chinese_readonly_phrases(
    tmp_path: Path, answer: str, expected: NetworkPolicy
) -> None:
    question_id = "permissions.network"
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: answer},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    assert reconciled.blueprint.decisions.network_policy.value is expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    (
        ("yes, you may use network for read-only access", NetworkPolicy.ALLOWED_READONLY),
        ("you may access the network read-only", NetworkPolicy.ALLOWED_READONLY),
        ("allowed to access the network read-only", NetworkPolicy.ALLOWED_READONLY),
        (
            "permit the tool to access the network read-only",
            NetworkPolicy.ALLOWED_READONLY,
        ),
        ("approve use network for read-only access", NetworkPolicy.ALLOWED_READONLY),
        ("yes, you may use network", NetworkPolicy.ALLOWED),
        ("you may access the network", NetworkPolicy.ALLOWED),
    ),
)
def test_reconcile_preserves_direct_network_readonly_restrictions(
    tmp_path: Path, answer: str, expected: NetworkPolicy
) -> None:
    question_id = "permissions.network"
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: answer},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    assert reconciled.blueprint.decisions.network_policy.value is expected


@pytest.mark.parametrize(
    ("question_id", "answer"),
    (
        ("permissions.network", "you may execute commands"),
        ("permissions.network", "yes, you may change project files"),
        ("permissions.network", "allow the tool to read local files"),
        ("permissions.write_project", "you may execute commands"),
        ("permissions.write_project", "you may access the network"),
        ("permissions.execute_command", "yes, you may change project files"),
        ("permissions.execute_command", "you may access the network"),
    ),
)
def test_reconcile_rejects_cross_field_permission_phrases(
    tmp_path: Path, question_id: str, answer: str
) -> None:
    reconciled = _reconcile_answers(
        model_result(tmp_path),
        {question_id: answer},
        {question_id: FieldProvenance.USER_RESPONSE},
        set(),
    )

    field = question_id.removeprefix("permissions.")
    if field == "network":
        assert reconciled.blueprint.decisions.network_policy.value is NetworkPolicy.UNKNOWN
    else:
        assert getattr(reconciled.blueprint.decisions, field).value is TriState.UNKNOWN


@pytest.mark.parametrize(
    ("answer", "expected"),
    (
        ("yes", NetworkPolicy.ALLOWED),
        ("no network access", NetworkPolicy.DENIED),
        ("read-only network access is okay", NetworkPolicy.ALLOWED_READONLY),
        ("只允许只读网络访问", NetworkPolicy.ALLOWED_READONLY),
        ("network access might be useful", NetworkPolicy.UNKNOWN),
    ),
)
def test_reconcile_maps_network_without_granting_discovery(
    tmp_path: Path, answer: str, expected: NetworkPolicy
) -> None:
    question_id = "permissions.network"
    result = model_result(tmp_path)
    result = result.model_copy(
        update={
            "blueprint": result.blueprint.model_copy(
                update={
                    "decisions": ProjectDecisions(
                        discovery_approval=AuthorizationState.APPROVED
                    )
                }
            )
        }
    )
    reconciled = _reconcile_answers(
        result,
        {question_id: answer},
        {question_id: FieldProvenance.RECOMMENDED_DEFAULT},
        set(),
    )

    decision = reconciled.blueprint.decisions.network_policy
    assert decision.value is expected
    assert decision.provenance.source is DecisionSource.RECOMMENDED_DEFAULT
    assert decision.provenance.reference == question_id
    assert reconciled.blueprint.decisions.discovery_approval is AuthorizationState.APPROVED


def test_reconcile_without_network_answer_preserves_unknown_policy(tmp_path: Path) -> None:
    result = model_result(tmp_path)
    model_decisions = ProjectDecisions(
        read_project=PermissionDecision(value=TriState.ALLOWED),
        network_policy=NetworkDecision(value=NetworkPolicy.ALLOWED),
        discovery_approval=AuthorizationState.APPROVED,
    )
    result = result.model_copy(
        update={
            "blueprint": result.blueprint.model_copy(
                update={"decisions": model_decisions}
            )
        }
    )

    reconciled = _reconcile_answers(result, {}, {}, set())

    assert reconciled.blueprint.decisions.network_policy.value is NetworkPolicy.UNKNOWN
    assert reconciled.blueprint.decisions.discovery_approval is AuthorizationState.APPROVED
    assert reconciled.blueprint.decisions.read_project.value is TriState.ALLOWED


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
async def test_missing_final_agent_message_uses_exec_fallback(tmp_path: Path) -> None:
    repository = snapshot(tmp_path)
    interview = build_interview(
        InterviewInput(repository=repository, unknowns=("project.goal",))
    )
    invocation = tmp_path / "exec.json"
    runner = ConversationRunner(
        app_server_command=app_command("missing-final-message", tmp_path / "server.json"),
        exec_fallback=fallback("structured-project", invocation),
    )

    result = await runner.run(
        repository=repository,
        interview=interview,
        ask_user=lambda _question: "User-confirmed goal",
    )

    assert invocation.exists()
    assert result.blueprint.goal == "User-confirmed goal"
    assert result.field_sources["goal"].value == "confirmed"


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
    interview = build_interview(InterviewInput(repository=repository, unknowns=("project.goal",)))
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


@pytest.mark.anyio
async def test_interrupted_interview_replays_two_answers_without_reasking(
    tmp_path: Path,
) -> None:
    from vibe.workflows.checkpoints import SqliteCheckpointStore
    from vibe.workflows.init_graph import InitializationGraph
    from vibe.workflows.state import InitStage

    repository = snapshot(tmp_path)
    interview = InterviewResult(
        questions=tuple(
            InterviewQuestion(question_id=question_id, category="fixture", text=question_id)
            for question_id in (
                "project.goal",
                "project.lifecycle",
                "risk.tolerance",
                "constraints.compliance",
            )
        ),
        confirmed_fact_keys=(),
        unresolved_keys=(
            "project.goal",
            "project.lifecycle",
            "risk.tolerance",
            "constraints.compliance",
        ),
    )
    store = SqliteCheckpointStore(tmp_path / "checkpoints.sqlite3")
    workflow = InitializationGraph(store)
    workflow.start("run-1", repository_digest=repository.source_digest)
    workflow.advance("run-1", InitStage.INVENTORY)
    workflow.advance("run-1", InitStage.INTERVIEW)
    first_answers = iter(("Ship safely", "active-development"))

    def interrupt_after_two(_question: InterviewQuestion) -> str:
        try:
            return next(first_answers)
        except StopIteration as exc:
            raise RuntimeError("simulated process interruption") from exc

    first = ConversationRunner(
        app_server_command=app_command("valid", tmp_path / "first.json"),
        exec_fallback=fallback("fail-if-called", tmp_path / "exec.json"),
    )
    with pytest.raises(BaseExceptionGroup, match="unhandled errors") as interrupted:
        await first.run(
            repository=repository,
            interview=interview,
            ask_user=interrupt_after_two,
            checkpoint_store=store,
            run_id="run-1",
        )
    assert "simulated process interruption" in repr(interrupted.value)

    asked_after_resume: list[str] = []
    remaining = iter(("high", "SOC 2"))
    second = ConversationRunner(
        app_server_command=app_command("lost-thread", tmp_path / "second.json"),
        exec_fallback=fallback("fail-if-called", tmp_path / "exec.json"),
    )

    def ask_remaining(question: InterviewQuestion) -> str:
        asked_after_resume.append(question.question_id)
        return next(remaining)

    result = await second.run(
        repository=repository,
        interview=interview,
        ask_user=ask_remaining,
        checkpoint_store=store,
        run_id="run-1",
    )

    assert asked_after_resume == ["risk.tolerance", "constraints.compliance"]
    assert result.blueprint.goal == "Ship safely"
    assert result.blueprint.lifecycle_stage.value == "active-development"
    assert result.blueprint.risk_level.value == "high"
    prompts = json.loads((tmp_path / "second.json").read_text())["prompts"]
    replayed = [json.loads(prompt) for prompt in prompts[1:3]]
    assert [item["question_id"] for item in replayed] == [
        "project.goal",
        "project.lifecycle",
    ]
