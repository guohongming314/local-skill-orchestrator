from __future__ import annotations

import hashlib
import json

import pytest
import yaml
from pydantic import ValidationError

from tests.materialize.test_templates import inputs, requirements
from vibe.materialize.project_hooks import ProjectHookPolicy, render_project_hooks
from vibe.materialize.templates import CapabilityLock, render_project_configuration


def test_approved_policy_renders_only_explicit_events_deterministically() -> None:
    policy = ProjectHookPolicy(
        events=("Stop", "PreToolUse"),
        command="python3 .ai-project/hooks/governance.py",
        permissions=("execute-command",),
        approved=True,
        approval_provenance="review:change-42",
        trust_digest="sha256:trusted-project-state",
    )

    rendered = render_project_hooks(policy)

    assert tuple(item.path for item in rendered.files) == (".codex/hooks.json",)
    content = rendered.files[0].content
    assert json.loads(content) == {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "command": "python3 .ai-project/hooks/governance.py",
                            "type": "command",
                        }
                    ],
                    "permissions": ["execute-command"],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "command": "python3 .ai-project/hooks/governance.py",
                            "type": "command",
                        }
                    ],
                    "permissions": ["execute-command"],
                }
            ],
        }
    }
    assert "UserPromptSubmit" not in content
    assert rendered.content_digest == hashlib.sha256(content.encode()).hexdigest()


def test_unapproved_policy_renders_no_hook_configuration() -> None:
    rendered = render_project_hooks(ProjectHookPolicy(events=("Stop",), command="python3 hook.py"))

    assert rendered.files == ()
    assert rendered.content_digest is None


def test_hook_digest_changes_with_definition() -> None:
    first = render_project_hooks(
        ProjectHookPolicy(events=("Stop",), command="python3 hook.py", approved=True)
    )
    second = render_project_hooks(
        ProjectHookPolicy(events=("PreToolUse",), command="python3 hook.py", approved=True)
    )

    assert first.content_digest != second.content_digest


@pytest.mark.parametrize(
    "command",
    (
        "python3 ../hook.py",
        "python3 /tmp/hook.py",
        "./../hook.py",
    ),
)
def test_hook_command_rejects_paths_outside_project(command: str) -> None:
    with pytest.raises(ValidationError):
        ProjectHookPolicy(events=("Stop",), command=command, approved=True)


def test_hook_policy_rejects_unknown_events_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectHookPolicy(events=("SessionStart",), command="python3 hook.py")
    with pytest.raises(ValidationError):
        ProjectHookPolicy(events=("Stop",), command="python3 hook.py", semantic_router=True)


def test_project_configuration_records_approved_hook_trust_in_lock() -> None:
    blueprint, plan, inventory = inputs()
    policy = ProjectHookPolicy(
        events=("PermissionRequest", "Stop"),
        command="python3 .ai-project/hooks/governance.py",
        permissions=("execute-command", "read-project"),
        approved=True,
        approval_provenance="review:security-17",
        trust_digest="sha256:project-reviewed",
    )

    rendered = render_project_configuration(
        blueprint, plan, inventory, requirements=requirements(), hook_policy=policy
    )
    files = rendered.as_dict()
    lock = CapabilityLock.model_validate(yaml.safe_load(files[".ai-project/capabilities.lock"]))
    hook = next(item for item in lock.providers if item.provider_id == "hook.project")

    assert ".codex/hooks.json" in files
    assert hook.content_digest == hashlib.sha256(files[".codex/hooks.json"].encode()).hexdigest()
    assert hook.hook_approved is True
    assert hook.hook_approval_provenance == "review:security-17"
    assert hook.hook_trust_digest == "sha256:project-reviewed"
    assert hook.hook_events == ("PermissionRequest", "Stop")
    assert hook.hook_permissions == ("execute-command", "read-project")
