"""Drive a project interview through one deny-by-default Codex thread."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import anyio

from vibe.codex.app_server import CodexAppServerClient, agent_message_text
from vibe.codex.approvals import ApprovalPolicy, decide_approval, parse_approval
from vibe.codex.exec_fallback import (
    CodexExecFallback,
    StructuredResultError,
    validate_structured_result,
)
from vibe.codex.jsonrpc import JsonRpcSubprocessClient
from vibe.conversation.interview import InterviewQuestion, InterviewResult
from vibe.conversation.structured_result import (
    DecisionLockedError,
    FieldProvenance,
    StructuredProjectResult,
    ValueSource,
    apply_revision,
    lock_decisions,
)
from vibe.models.repository import RepositorySnapshot
from vibe.workflows.checkpoints import SqliteCheckpointStore

AskUser = Callable[[InterviewQuestion], str]

_QUESTION_FIELDS = {
    "project.goal": "goal",
    "project.lifecycle": "lifecycle_stage",
    "risk.tolerance": "risk_level",
}
_ACCEPT_DEFAULT = {"accept", "accept default", "use default"}


class ConversationRunner:
    """Collect natural-language answers and request one validated project result."""

    def __init__(
        self,
        *,
        app_server_command: Sequence[str] = ("codex", "app-server"),
        exec_fallback: CodexExecFallback | None = None,
        timeout: float = 300.0,
    ) -> None:
        self._app_server_command = tuple(app_server_command)
        self._exec_fallback = exec_fallback or CodexExecFallback()
        self._timeout = timeout

    async def run(
        self,
        *,
        repository: RepositorySnapshot,
        interview: InterviewResult,
        ask_user: AskUser,
        checkpoint_store: SqliteCheckpointStore | None = None,
        run_id: str | None = None,
    ) -> StructuredProjectResult:
        """Run the interview turns, falling back once when final output is malformed."""
        prompt = _context_prompt(repository, interview)
        if (checkpoint_store is None) != (run_id is None):
            raise ValueError("checkpoint_store and run_id must be provided together")
        answers: dict[str, str] = {}
        provenance: dict[str, FieldProvenance] = {}
        locked_questions: set[str] = set()
        saved_thread_id: str | None = None
        if checkpoint_store is not None and run_id is not None:
            progress = checkpoint_store.load_interview_progress(run_id)
            saved_thread_id = progress.thread_id
            answers.update(progress.answers)
            provenance.update(
                {key: FieldProvenance(value) for key, value in progress.provenance.items()}
            )
            locked_questions.update(progress.locked_questions)
        async with JsonRpcSubprocessClient(self._app_server_command) as transport:
            client = CodexAppServerClient(transport)
            await client.initialize()
            resumed = False
            if saved_thread_id is not None:
                try:
                    thread = await client.resume_thread(saved_thread_id)
                    resumed = True
                except Exception:
                    thread = await client.start_thread(cwd=repository.root)
            else:
                thread = await client.start_thread(cwd=repository.root)
            if checkpoint_store is not None and run_id is not None:
                checkpoint_store.save_interview_progress(
                    run_id,
                    thread_id=thread.id,
                    answers=answers,
                    provenance={key: value.value for key, value in provenance.items()},
                    locked_questions=frozenset(locked_questions),
                )
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(_deny_approval_requests, transport)
                try:
                    if not resumed:
                        await client.run_turn(thread.id, prompt, timeout=self._timeout)
                        for question_id, answer in answers.items():
                            await client.run_turn(
                                thread.id,
                                _answer_prompt(
                                    question_id,
                                    answer,
                                    provenance[question_id],
                                    question_id in locked_questions,
                                ),
                                timeout=self._timeout,
                            )
                    index = 0
                    questions = interview.questions
                    while index < len(questions):
                        question = questions[index]
                        if question.question_id in answers:
                            index += 1
                            continue
                        response = ask_user(question).strip()
                        command, _, argument = response.partition(" ")
                        if command.lower() == "revise" and argument:
                            target = _question_index(questions, argument)
                            if argument in locked_questions:
                                raise DecisionLockedError(
                                    f"cannot revise locked decision: {argument}"
                                )
                            for stale in questions[target:]:
                                answers.pop(stale.question_id, None)
                                provenance.pop(stale.question_id, None)
                            index = target
                            continue
                        if command.lower() == "lock" and argument:
                            if argument not in answers:
                                raise ValueError(f"cannot lock unanswered question: {argument}")
                            if argument not in _QUESTION_FIELDS:
                                raise ValueError(f"question cannot be locked: {argument}")
                            locked_questions.add(argument)
                            continue
                        if response.lower() in _ACCEPT_DEFAULT:
                            if question.recommended_default is None:
                                raise ValueError(
                                    f"question has no recommended default: {question.question_id}"
                                )
                            answer = question.recommended_default
                            answer_provenance = FieldProvenance.RECOMMENDED_DEFAULT
                        else:
                            answer = response
                            answer_provenance = FieldProvenance.USER_RESPONSE
                        answers[question.question_id] = answer
                        provenance[question.question_id] = answer_provenance
                        await client.run_turn(
                            thread.id,
                            _answer_prompt(
                                question.question_id,
                                answer,
                                answer_provenance,
                                question.question_id in locked_questions,
                            ),
                            timeout=self._timeout,
                        )
                        if checkpoint_store is not None and run_id is not None:
                            checkpoint_store.save_interview_progress(
                                run_id,
                                thread_id=thread.id,
                                answers=answers,
                                provenance={key: value.value for key, value in provenance.items()},
                                locked_questions=frozenset(locked_questions),
                            )
                        index += 1
                    final_turn = await client.run_turn(
                        thread.id,
                        json.dumps(
                            {
                                "instruction": (
                                    "Return the final StructuredProjectResult as JSON matching "
                                    "the supplied schema. Do not overwrite locked decisions."
                                ),
                                "answers": answers,
                                "locked_questions": sorted(locked_questions),
                            },
                            sort_keys=True,
                        ),
                        timeout=self._timeout,
                        output_schema=StructuredProjectResult.model_json_schema(),
                    )
                finally:
                    tasks.cancel_scope.cancel()
        try:
            result = validate_structured_result(
                agent_message_text(final_turn),
                StructuredProjectResult,
                source="app-server output",
            )
        except StructuredResultError:
            result = await self._exec_fallback.run(
                prompt=(
                    f"{prompt}\nReturn the final StructuredProjectResult as schema-valid JSON."
                ),
                model_type=StructuredProjectResult,
                cwd=repository.root,
            )
        return _reconcile_answers(result, answers, provenance, locked_questions)


def _answer_prompt(question_id: str, answer: str, provenance: FieldProvenance, locked: bool) -> str:
    return json.dumps(
        {
            "question_id": question_id,
            "answer": answer,
            "provenance": provenance.value,
            "locked": locked,
        },
        sort_keys=True,
    )


def _question_index(questions: tuple[InterviewQuestion, ...], question_id: str) -> int:
    for index, question in enumerate(questions):
        if question.question_id == question_id:
            return index
    raise ValueError(f"unknown revision question: {question_id}")


def _reconcile_answers(
    result: StructuredProjectResult,
    answers: dict[str, str],
    provenance: dict[str, FieldProvenance],
    locked_questions: set[str],
) -> StructuredProjectResult:
    updates = {
        field: answers[question_id]
        for question_id, field in _QUESTION_FIELDS.items()
        if question_id in answers
    }
    local_fields = set(updates)
    unlocked = result.model_copy(
        update={"locked_decisions": result.locked_decisions - local_fields}
    )
    if updates:
        unlocked = apply_revision(unlocked, updates, source=ValueSource.CONFIRMED)
    field_provenance = dict(unlocked.field_provenance)
    field_provenance.update(
        {
            _QUESTION_FIELDS[question_id]: answer_provenance
            for question_id, answer_provenance in provenance.items()
            if question_id in _QUESTION_FIELDS
        }
    )
    reconciled = unlocked.model_copy(update={"field_provenance": field_provenance})
    lock_fields = tuple(_QUESTION_FIELDS[item] for item in sorted(locked_questions))
    if lock_fields:
        reconciled = lock_decisions(reconciled, *lock_fields)
    model_locks = result.locked_decisions - local_fields
    return reconciled.model_copy(
        update={"locked_decisions": reconciled.locked_decisions | model_locks}
    )


def _context_prompt(repository: RepositorySnapshot, interview: InterviewResult) -> str:
    return json.dumps(
        {
            "instruction": (
                "Conduct this project interview without executing commands, changing files, "
                "or using network access. Preserve the user's natural-language answers for "
                "the final structured result."
            ),
            "repository": repository.model_dump(mode="json"),
            "questions": [
                {
                    "id": question.question_id,
                    "text": question.text,
                    "category": question.category,
                    "requires_explicit_confirmation": question.requires_explicit_confirmation,
                    "recommended_default": question.recommended_default,
                    "recommendation_reason": question.recommendation_reason,
                }
                for question in interview.questions
            ],
        },
        sort_keys=True,
    )


async def _deny_approval_requests(transport: JsonRpcSubprocessClient) -> None:
    policy = ApprovalPolicy()
    while True:
        request = await transport.receive_server_request()
        decision = decide_approval(parse_approval(request), policy)
        await transport.respond(request.id, decision.response)
