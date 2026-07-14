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
from vibe.conversation.structured_result import StructuredProjectResult
from vibe.models.repository import RepositorySnapshot

AskUser = Callable[[InterviewQuestion], str]


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
    ) -> StructuredProjectResult:
        """Run the interview turns, falling back once when final output is malformed."""
        prompt = _context_prompt(repository, interview)
        async with JsonRpcSubprocessClient(self._app_server_command) as transport:
            client = CodexAppServerClient(transport)
            await client.initialize()
            thread = await client.start_thread(cwd=repository.root)
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(_deny_approval_requests, transport)
                try:
                    await client.run_turn(thread.id, prompt, timeout=self._timeout)
                    for question in interview.questions:
                        answer = ask_user(question)
                        await client.run_turn(
                            thread.id,
                            json.dumps(
                                {"question_id": question.question_id, "answer": answer},
                                sort_keys=True,
                            ),
                            timeout=self._timeout,
                        )
                    final_turn = await client.run_turn(
                        thread.id,
                        (
                            "Return the final StructuredProjectResult as JSON matching "
                            "the supplied schema."
                        ),
                        timeout=self._timeout,
                        output_schema=StructuredProjectResult.model_json_schema(),
                    )
                finally:
                    tasks.cancel_scope.cancel()
        try:
            return validate_structured_result(
                agent_message_text(final_turn),
                StructuredProjectResult,
                source="app-server output",
            )
        except StructuredResultError:
            return await self._exec_fallback.run(
                prompt=(
                    f"{prompt}\nReturn the final StructuredProjectResult as schema-valid JSON."
                ),
                model_type=StructuredProjectResult,
                cwd=repository.root,
            )


def _context_prompt(
    repository: RepositorySnapshot, interview: InterviewResult
) -> str:
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
                    "requires_explicit_confirmation": question.requires_explicit_confirmation,
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
