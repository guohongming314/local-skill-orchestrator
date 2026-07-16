"""Approval-gated rendering for managed project-local Codex Hooks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProjectHookEvent = Literal[
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
]

_SCRIPT_PATH = re.compile(r"^\.ai-project/hooks/[A-Za-z0-9][A-Za-z0-9._-]*\.py$")


class ProjectHookPolicy(BaseModel):
    """Explicit approval for one managed project hook script."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    events: tuple[ProjectHookEvent, ...] = Field(min_length=1)
    script_path: str = Field(min_length=1)
    script_content: str = Field(min_length=1)
    permissions: tuple[str, ...] = ("execute-command",)
    approved: bool = False
    approval_provenance: str | None = None

    @field_validator("script_path")
    @classmethod
    def managed_script_path(cls, value: str) -> str:
        if not _SCRIPT_PATH.fullmatch(value):
            raise ValueError("Hook script must be a normalized .ai-project/hooks/*.py path")
        return value

    @model_validator(mode="after")
    def approved_policy_has_provenance(self) -> ProjectHookPolicy:
        if self.approved and not (self.approval_provenance or "").strip():
            raise ValueError("approved Hook policy requires approval provenance")
        return self


@dataclass(frozen=True, order=True)
class HookRenderedFile:
    path: str
    content: str


@dataclass(frozen=True)
class RenderedProjectHooks:
    files: tuple[HookRenderedFile, ...]
    content_digest: str | None = None
    script_digest: str | None = None
    trust_digest: str | None = None


def render_project_hooks(policy: ProjectHookPolicy) -> RenderedProjectHooks:
    """Render canonical Hook metadata and its managed script after approval."""
    if not policy.approved:
        return RenderedProjectHooks(files=())
    command = _managed_command(policy.script_path)
    entry = {"hooks": [{"command": command, "type": "command"}]}
    payload = {"hooks": {event: [entry] for event in sorted(set(policy.events))}}
    hooks_content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    hooks_digest = hashlib.sha256(hooks_content.encode("utf-8")).hexdigest()
    script_digest = hashlib.sha256(policy.script_content.encode("utf-8")).hexdigest()
    trust_digest = combined_hook_trust_digest(
        hooks_content.encode("utf-8"),
        policy.script_path,
        policy.script_content.encode("utf-8"),
    )
    return RenderedProjectHooks(
        files=(
            HookRenderedFile(path=policy.script_path, content=policy.script_content),
            HookRenderedFile(path=".codex/hooks.json", content=hooks_content),
        ),
        content_digest=hooks_digest,
        script_digest=script_digest,
        trust_digest=trust_digest,
    )


def combined_hook_trust_digest(hooks_bytes: bytes, script_path: str, script_bytes: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(hooks_bytes)
    digest.update(b"\0")
    digest.update(script_path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(script_bytes)
    return digest.hexdigest()


def _managed_command(script_path: str) -> str:
    return f'python3 "$(git rev-parse --show-toplevel)/{script_path}"'
