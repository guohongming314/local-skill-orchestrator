from __future__ import annotations

import hashlib
import json

import pytest
import yaml

from tests.e2e.codex_native_fixture import CodexNativeProjectFixture, native_project

__all__ = ["native_project"]


def test_init_generates_codex_native_discoverable_project_capabilities(
    native_project: CodexNativeProjectFixture,
) -> None:
    result = native_project.initialize(selected_skill="systematic-debugging")

    assert result.exit_code == 0, result.output
    manager = native_project.root / ".agents/skills/project-capability-manager/SKILL.md"
    debugging = native_project.root / ".agents/skills/systematic-debugging/SKILL.md"
    assert manager.is_file()
    assert debugging.is_file()
    assert native_project.discoverable_skill_names() == (
        "project-capability-manager",
        "systematic-debugging",
    )
    assert native_project.skill_metadata_is_valid(manager)
    assert native_project.skill_metadata_is_valid(debugging)
    debugging_frontmatter = native_project.skill_metadata(debugging)
    assert debugging_frontmatter["description"] == (
        "Diagnose intermittent failures and verify bug fixes"
    )
    assert debugging_frontmatter["provides"] == "quality.gates"
    lock = yaml.safe_load(
        (native_project.root / ".ai-project/capabilities.lock").read_text(encoding="utf-8")
    )
    assert any(
        item["provider_id"] == "skill.systematic-debugging"
        for item in lock["providers"]
    )
    agents = (native_project.root / "AGENTS.md").read_text(encoding="utf-8")
    assert "vibe run" not in agents


def test_missing_capability_install_stays_in_current_codex_conversation(
    native_project: CodexNativeProjectFixture,
) -> None:
    native_project.initialize(selected_skill="systematic-debugging")
    session = native_project.start_session()
    original_thread_id = session.thread_id
    original_observed_threads = session.observed_thread_ids
    assert original_thread_id == "thread-persisted"
    assert native_project.observed_process_starts == 1
    assert native_project.observed_thread_starts == 1
    assert native_project.fake_host_state()["threadId"] == original_thread_id

    session.request("Validate the browser checkout flow")
    session.approve_project_candidate("browser-testing")

    assert session.thread_id == original_thread_id
    assert session.observed_thread_ids == original_observed_threads
    assert native_project.observed_process_starts == 1
    assert native_project.observed_thread_starts == 1
    assert session.started_nested_codex_processes == 0
    assert session.started_nested_codex_threads == 0
    assert session.internal_commands == ("init", "install")
    assert session.loaded_skill_names == (
        "project-capability-manager",
        "browser-testing",
    )
    assert (native_project.root / ".agents/skills/browser-testing/SKILL.md").is_file()


def test_sufficient_existing_capabilities_do_not_invoke_vibe_task_router(
    native_project: CodexNativeProjectFixture,
) -> None:
    native_project.initialize(selected_skill="systematic-debugging")
    session = native_project.start_session()

    assert "Use Codex-native Skill discovery" in session.agents_md
    assert {item.name for item in session.discovered_skills} == {
        "project-capability-manager",
        "systematic-debugging",
    }
    session.request("Fix the intermittent login failure")

    assert session.loaded_skill_names == ("systematic-debugging",)
    assert "route-task" not in session.internal_commands
    assert session.internal_commands == ("init",)
    assert session.started_nested_codex_processes == 0
    assert session.started_nested_codex_threads == 0


def test_optional_hook_governance_does_not_change_native_skill_discovery(
    native_project: CodexNativeProjectFixture,
) -> None:
    native_project.initialize(selected_skill="systematic-debugging")
    assert not (native_project.root / ".codex/hooks.json").exists()

    native_project.install_approved_hook()
    session = native_project.start_session()
    assert session.configured_hook_events == ("PreToolUse", "Stop")
    assert "UserPromptSubmit" not in session.configured_hook_events
    session.request("Fix the intermittent login failure")

    hooks = json.loads(
        (native_project.root / ".codex/hooks.json").read_text(encoding="utf-8")
    )
    assert set(hooks["hooks"]) == {"PreToolUse", "Stop"}
    command = (
        'python3 "$(git rev-parse --show-toplevel)/'
        '.ai-project/hooks/governance.py"'
    )
    assert hooks == {
        "hooks": {
            event: [{"hooks": [{"command": command, "type": "command"}]}]
            for event in ("PreToolUse", "Stop")
        }
    }
    assert "permissions" not in json.dumps(hooks)
    script = native_project.root / ".ai-project/hooks/governance.py"
    assert script.read_text(encoding="utf-8") == "print('governance')\n"
    hook_lock = native_project.hook_lock_entry()
    assert hook_lock["hook_approved"] is True
    assert hook_lock["hook_approval_provenance"] == "acceptance:attended-review"
    assert hook_lock["hook_events"] == ["PreToolUse", "Stop"]
    assert hook_lock["hook_permissions"] == ["execute-command"]
    assert hook_lock["hook_script_path"] == ".ai-project/hooks/governance.py"
    assert hook_lock["content_digest"] == hashlib.sha256(
        (native_project.root / ".codex/hooks.json").read_bytes()
    ).hexdigest()
    assert hook_lock["hook_script_digest"] == hashlib.sha256(script.read_bytes()).hexdigest()
    assert hook_lock["hook_trust_digest"] == native_project.installed_hook_trust_digest()
    assert session.loaded_skill_names == ("systematic-debugging",)
    assert session.started_nested_codex_processes == 0
    assert session.started_nested_codex_threads == 0


def test_nested_codex_boundaries_are_recorded_and_rejected(
    native_project: CodexNativeProjectFixture,
) -> None:
    native_project.initialize(selected_skill="systematic-debugging")
    native_project.start_session()

    with pytest.raises(AssertionError, match="nested Codex process"):
        native_project.attempt_nested_process_start()
    with pytest.raises(AssertionError, match="nested Codex thread"):
        native_project.attempt_nested_thread_start()

    assert native_project.observed_process_starts == 2
    assert native_project.observed_thread_starts == 2
