"""Deny-by-default parsing and policy decisions for Codex server requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from vibe.codex.protocol import JsonObject, JsonRpcId, JsonRpcServerRequest, JsonValue


class ApprovalProtocolError(ValueError):
    """A known approval request does not satisfy its protocol contract."""


class ApprovalKind(StrEnum):
    COMMAND = "command"
    FILE_CHANGE = "file_change"
    PERMISSIONS = "permissions"
    DYNAMIC_TOOL = "dynamic_tool"
    UNKNOWN = "unknown"


class ApprovalOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    PROMPT = "prompt"


_METHOD_KINDS = {
    "item/commandExecution/requestApproval": ApprovalKind.COMMAND,
    "item/fileChange/requestApproval": ApprovalKind.FILE_CHANGE,
    "item/permissions/requestApproval": ApprovalKind.PERMISSIONS,
    "item/tool/call": ApprovalKind.DYNAMIC_TOOL,
}


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    request_id: JsonRpcId
    method: str
    kind: ApprovalKind
    thread_id: str | None
    turn_id: str | None
    item_id: str | None
    tool_name: str | None
    requested_permissions: JsonObject | None


@dataclass(frozen=True, slots=True)
class ApprovalAuditRecord:
    """Allowlisted metadata only; raw command, output, arguments, and secrets are excluded."""

    request_id: JsonRpcId
    method: str
    kind: ApprovalKind
    outcome: ApprovalOutcome
    thread_id: str | None
    turn_id: str | None
    item_id: str | None
    tool_name: str | None


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    outcome: ApprovalOutcome
    response: JsonObject | None
    audit: ApprovalAuditRecord


class ApprovalPolicy:
    """Explicit per-kind outcomes with deny as the immutable fallback."""

    def __init__(self, outcomes: Mapping[ApprovalKind, ApprovalOutcome] | None = None) -> None:
        self._outcomes = dict(outcomes or {})

    def outcome_for(self, kind: ApprovalKind) -> ApprovalOutcome:
        if kind is ApprovalKind.UNKNOWN:
            return ApprovalOutcome.DENY
        return self._outcomes.get(kind, ApprovalOutcome.DENY)


def parse_approval(server_request: JsonRpcServerRequest) -> ApprovalRequest:
    """Classify and minimally validate a Codex approval or dynamic-tool request."""
    kind = _METHOD_KINDS.get(server_request.method, ApprovalKind.UNKNOWN)
    if kind is ApprovalKind.UNKNOWN:
        return ApprovalRequest(
            server_request.id,
            server_request.method,
            kind,
            None,
            None,
            None,
            None,
            None,
        )
    params = _expect_object(server_request.params, f"{server_request.method} params")
    thread_id = _required_string(params, "threadId")
    turn_id = _required_string(params, "turnId")
    item_id: str | None = None
    tool_name: str | None = None
    requested_permissions: JsonObject | None = None
    if kind is ApprovalKind.DYNAMIC_TOOL:
        item_id = _required_string(params, "callId")
        tool_name = _required_string(params, "tool")
    else:
        item_id = _required_string(params, "itemId")
    if kind is ApprovalKind.PERMISSIONS:
        requested_permissions = _expect_object(params.get("permissions"), "permissions")
    return ApprovalRequest(
        server_request.id,
        server_request.method,
        kind,
        thread_id,
        turn_id,
        item_id,
        tool_name,
        requested_permissions,
    )


def decide_approval(request: ApprovalRequest, policy: ApprovalPolicy) -> ApprovalDecision:
    """Apply policy and produce a protocol response plus redacted audit metadata."""
    outcome = policy.outcome_for(request.kind)
    response = _response_for(request, outcome)
    audit = ApprovalAuditRecord(
        request_id=request.request_id,
        method=request.method,
        kind=request.kind,
        outcome=outcome,
        thread_id=request.thread_id,
        turn_id=request.turn_id,
        item_id=request.item_id,
        tool_name=request.tool_name,
    )
    return ApprovalDecision(outcome=outcome, response=response, audit=audit)


def _response_for(request: ApprovalRequest, outcome: ApprovalOutcome) -> JsonObject | None:
    if outcome is ApprovalOutcome.PROMPT:
        return None
    if request.kind in {ApprovalKind.COMMAND, ApprovalKind.FILE_CHANGE}:
        return {"decision": "accept" if outcome is ApprovalOutcome.ALLOW else "decline"}
    if request.kind is ApprovalKind.PERMISSIONS:
        permissions = request.requested_permissions if outcome is ApprovalOutcome.ALLOW else {}
        return {"permissions": permissions or {}, "scope": "turn"}
    if request.kind is ApprovalKind.DYNAMIC_TOOL:
        if outcome is ApprovalOutcome.ALLOW:
            return None
        return {"contentItems": [], "success": False}
    return {"decision": "decline"}


def _expect_object(value: JsonValue | None, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ApprovalProtocolError(f"{label} must be an object")
    return value


def _required_string(value: JsonObject, key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ApprovalProtocolError(f"{key} must be a non-empty string")
    return item
