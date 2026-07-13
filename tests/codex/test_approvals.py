from __future__ import annotations

from vibe.codex.approvals import (
    ApprovalKind,
    ApprovalOutcome,
    ApprovalPolicy,
    decide_approval,
    parse_approval,
)
from vibe.codex.protocol import JsonObject, JsonRpcServerRequest


def request(method: str, params: JsonObject) -> JsonRpcServerRequest:
    return JsonRpcServerRequest(id=7, method=method, params=params)


def test_known_command_approval_maps_allow_to_accept() -> None:
    parsed = parse_approval(
        request(
            "item/commandExecution/requestApproval",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "startedAtMs": 123,
                "command": "uv run pytest",
            },
        )
    )
    decision = decide_approval(
        parsed, ApprovalPolicy({ApprovalKind.COMMAND: ApprovalOutcome.ALLOW})
    )

    assert parsed.kind is ApprovalKind.COMMAND
    assert decision.outcome is ApprovalOutcome.ALLOW
    assert decision.response == {"decision": "accept"}


def test_known_file_approval_maps_deny_to_decline() -> None:
    parsed = parse_approval(
        request(
            "item/fileChange/requestApproval",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-2",
                "startedAtMs": 456,
                "reason": "write outside cwd",
            },
        )
    )
    decision = decide_approval(
        parsed, ApprovalPolicy({ApprovalKind.FILE_CHANGE: ApprovalOutcome.DENY})
    )

    assert decision.response == {"decision": "decline"}


def test_permission_approval_can_require_explicit_user_prompt() -> None:
    parsed = parse_approval(
        request(
            "item/permissions/requestApproval",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-3",
                "startedAtMs": 789,
                "cwd": "C:/repo",
                "permissions": {"network": {"enabled": True}},
            },
        )
    )
    decision = decide_approval(
        parsed, ApprovalPolicy({ApprovalKind.PERMISSIONS: ApprovalOutcome.PROMPT})
    )

    assert decision.outcome is ApprovalOutcome.PROMPT
    assert decision.response is None


def test_dynamic_tool_is_classified_and_requires_prompt_when_configured() -> None:
    parsed = parse_approval(
        request(
            "item/tool/call",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "callId": "call-1",
                "tool": "deploy",
                "arguments": {"token": "secret-value"},
            },
        )
    )
    decision = decide_approval(
        parsed, ApprovalPolicy({ApprovalKind.DYNAMIC_TOOL: ApprovalOutcome.PROMPT})
    )

    assert parsed.kind is ApprovalKind.DYNAMIC_TOOL
    assert decision.outcome is ApprovalOutcome.PROMPT


def test_unknown_approval_kind_is_denied_by_default() -> None:
    parsed = parse_approval(request("future/dangerous/requestApproval", {"secret": "value"}))
    decision = decide_approval(parsed, ApprovalPolicy())

    assert parsed.kind is ApprovalKind.UNKNOWN
    assert decision.outcome is ApprovalOutcome.DENY
    assert decision.response == {"decision": "decline"}


def test_audit_record_omits_commands_outputs_arguments_and_secrets() -> None:
    secret = "sk-do-not-store"
    parsed = parse_approval(
        request(
            "item/commandExecution/requestApproval",
            {
                "threadId": "thread-9",
                "turnId": "turn-8",
                "itemId": "item-7",
                "startedAtMs": 123,
                "command": f"curl -H Authorization:{secret}",
                "output": f"server returned {secret}",
                "arguments": {"api_key": secret},
            },
        )
    )
    decision = decide_approval(parsed, ApprovalPolicy())
    serialized = repr(decision.audit)

    assert decision.audit.thread_id == "thread-9"
    assert decision.audit.item_id == "item-7"
    assert secret not in serialized
    assert "curl" not in serialized
    assert "server returned" not in serialized
    assert "api_key" not in serialized
