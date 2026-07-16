from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tests.materialize.test_templates import inputs, requirements
from vibe.doctor.checks import run_health_checks
from vibe.inventory.adapters.base import AdapterProvenance, AdapterScanResult, AdapterVerification
from vibe.inventory.service import InventoryResult
from vibe.materialize.project_hooks import ProjectHookPolicy, render_project_hooks
from vibe.materialize.templates import CapabilityLock, render_project_configuration
from vibe.models.blueprint import Blueprint
from vibe.models.capability import CapabilityKind, CapabilityManifest, CapabilityScope, Permission
from vibe.models.resolution import CapabilityResolution, ResolutionPlan, ResolutionStatus


def policy(**updates: object) -> ProjectHookPolicy:
    values: dict[str, object] = {
        "events": ("Stop", "PreToolUse"),
        "script_path": ".ai-project/hooks/governance.py",
        "script_content": "print('governance')\n",
        "permissions": ("execute-command",),
        "approved": True,
        "approval_provenance": "review:change-42",
    }
    values.update(updates)
    return ProjectHookPolicy.model_validate(values)


def test_approved_policy_renders_exact_events_script_and_fixed_command() -> None:
    rendered = render_project_hooks(policy())
    files = {item.path: item.content for item in rendered.files}

    assert tuple(item.path for item in rendered.files) == (
        ".ai-project/hooks/governance.py",
        ".codex/hooks.json",
    )
    assert files[".ai-project/hooks/governance.py"] == "print('governance')\n"
    command = 'python3 "$(git rev-parse --show-toplevel)/.ai-project/hooks/governance.py"'
    assert json.loads(files[".codex/hooks.json"]) == {
        "hooks": {
            "PreToolUse": [{"hooks": [{"command": command, "type": "command"}]}],
            "Stop": [{"hooks": [{"command": command, "type": "command"}]}],
        }
    }
    assert "permissions" not in files[".codex/hooks.json"]
    assert "UserPromptSubmit" not in files[".codex/hooks.json"]


def test_unapproved_policy_renders_no_files() -> None:
    rendered = render_project_hooks(policy(approved=False, approval_provenance=None))
    assert rendered.files == ()
    assert rendered.content_digest is None
    assert rendered.script_digest is None
    assert rendered.trust_digest is None


def test_json_script_and_combined_trust_digests_change_with_definition() -> None:
    first = render_project_hooks(policy())
    event_change = render_project_hooks(policy(events=("Stop",)))
    script_change = render_project_hooks(policy(script_content="print('changed')\n"))

    assert first.content_digest != event_change.content_digest
    assert first.script_digest == event_change.script_digest
    assert first.script_digest != script_change.script_digest
    assert len({first.trust_digest, event_change.trust_digest, script_change.trust_digest}) == 3


@pytest.mark.parametrize(
    "script_path",
    (
        "../hook.py",
        "/tmp/hook.py",
        ".ai-project/other/hook.py",
        ".ai-project/hooks/hook.sh",
        ".ai-project/hooks/../evil.py",
        ".ai-project/hooks/bad name.py",
    ),
)
def test_policy_rejects_unmanaged_script_paths(script_path: str) -> None:
    with pytest.raises(ValidationError):
        policy(script_path=script_path)


def test_policy_is_strict_requires_provenance_and_rejects_shell_command_input() -> None:
    with pytest.raises(ValidationError):
        policy(events=["Stop"])
    with pytest.raises(ValidationError):
        policy(approved=1)
    with pytest.raises(ValidationError):
        policy(approval_provenance=None)
    with pytest.raises(ValidationError):
        policy(command="sh -c 'evil'")
    with pytest.raises(ValidationError):
        policy(events=("SessionStart",))


def test_project_configuration_records_both_artifact_digests_and_combined_trust() -> None:
    blueprint, plan, inventory = inputs()
    rendered = render_project_configuration(
        blueprint, plan, inventory, requirements=requirements(), hook_policy=policy()
    )
    files = rendered.as_dict()
    lock = CapabilityLock.model_validate(yaml.safe_load(files[".ai-project/capabilities.lock"]))
    hook = next(item for item in lock.providers if item.provider_id == "hook.project")

    assert hook.source == ".codex/hooks.json"
    assert hook.hook_script_path == ".ai-project/hooks/governance.py"
    assert hook.content_digest == hashlib.sha256(files[hook.source].encode()).hexdigest()
    assert (
        hook.hook_script_digest == hashlib.sha256(files[hook.hook_script_path].encode()).hexdigest()
    )
    assert hook.hook_trust_digest not in {hook.content_digest, hook.hook_script_digest}
    assert hook.hook_permissions == ("execute-command",)


def _inputs_with_selected_project_hook() -> tuple[Blueprint, ResolutionPlan, InventoryResult]:
    blueprint, plan, inventory = inputs()
    manifest = CapabilityManifest(
        capability_id="hook.project",
        name="existing project hook",
        kind=CapabilityKind.HOOK,
        scope=CapabilityScope.PROJECT,
        source=".codex/hooks.json",
        provides=("trigger:Stop",),
        permissions=frozenset({Permission.EXECUTE_COMMAND}),
        content_digest="existing-hook-digest",
        verified=True,
    )
    current = InventoryResult(
        capabilities=(
            *inventory.capabilities,
            AdapterScanResult(
                manifest=manifest,
                provenance=AdapterProvenance("fixture", ".codex/hooks.json"),
                verification=AdapterVerification(True),
            ),
        ),
        diagnostics=inventory.diagnostics,
        inventory_digest=inventory.inventory_digest,
    )
    selected = plan.model_copy(
        update={
            "resolutions": (
                *plan.resolutions,
                CapabilityResolution(
                    requirement="hook-governance",
                    status=ResolutionStatus.SELECTED,
                    capability_id="hook.project",
                    reason="selected existing hook",
                ),
            )
        }
    )
    return blueprint, selected, current


def test_managed_hook_replaces_selected_inventory_hook_in_lock(tmp_path: Path) -> None:
    blueprint, plan, inventory = _inputs_with_selected_project_hook()
    rendered = render_project_configuration(
        blueprint, plan, inventory, requirements=requirements(), hook_policy=policy()
    )
    lock = CapabilityLock.model_validate(
        yaml.safe_load(rendered.as_dict()[".ai-project/capabilities.lock"])
    )

    hooks = tuple(item for item in lock.providers if item.provider_id == "hook.project")
    assert len(hooks) == 1
    assert hooks[0].hook_approved is True
    assert hooks[0].hook_script_digest
    assert hooks[0].hook_trust_digest
    for relative, content in rendered.as_dict().items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    report = run_health_checks(tmp_path, inventory, lambda command: command)
    assert not any(item.code.startswith("hook.") for item in report.findings)


def test_selected_inventory_hook_remains_ordinary_without_managed_policy() -> None:
    blueprint, plan, inventory = _inputs_with_selected_project_hook()
    rendered = render_project_configuration(blueprint, plan, inventory, requirements=requirements())
    lock = CapabilityLock.model_validate(
        yaml.safe_load(rendered.as_dict()[".ai-project/capabilities.lock"])
    )

    hook = next(item for item in lock.providers if item.provider_id == "hook.project")
    assert hook.content_digest == "existing-hook-digest"
    assert hook.hook_approved is None
