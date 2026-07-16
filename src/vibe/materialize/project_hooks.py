"""Approval-gated rendering for trusted project-local Codex Hooks."""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectHookEvent = Literal[
    "UserPromptSubmit",
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "Stop",
]


class ProjectHookPolicy(BaseModel):
    """Explicit approval and trust record for one project hook command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    events: tuple[ProjectHookEvent, ...] = Field(min_length=1)
    command: str = Field(min_length=1)
    permissions: tuple[str, ...] = ("execute-command",)
    approved: bool = False
    approval_provenance: str | None = None
    trust_digest: str | None = None

    @field_validator("command")
    @classmethod
    def command_paths_stay_in_project(cls, command: str) -> str:
        if not command.strip():
            raise ValueError("hook command must not be empty")
        try:
            parts = shlex.split(command)
        except ValueError as error:
            raise ValueError("hook command must be valid shell words") from error
        if not parts:
            raise ValueError("hook command must not be empty")
        for index, part in enumerate(parts):
            if part.startswith("-"):
                continue
            looks_like_path = index > 0 or "/" in part or part.startswith(".")
            if not looks_like_path:
                continue
            path = PurePosixPath(part)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("hook command paths must stay within the project")
        return command


@dataclass(frozen=True, order=True)
class HookRenderedFile:
    path: str
    content: str


@dataclass(frozen=True)
class RenderedProjectHooks:
    files: tuple[HookRenderedFile, ...]
    content_digest: str | None = None


def render_project_hooks(policy: ProjectHookPolicy) -> RenderedProjectHooks:
    """Render exact project Hook configuration only after explicit approval."""
    if not policy.approved:
        return RenderedProjectHooks(files=())
    entry = {
        "hooks": [{"command": policy.command, "type": "command"}],
        "permissions": sorted(set(policy.permissions)),
    }
    payload = {"hooks": {event: [entry] for event in sorted(set(policy.events))}}
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return RenderedProjectHooks(
        files=(HookRenderedFile(path=".codex/hooks.json", content=content),),
        content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
