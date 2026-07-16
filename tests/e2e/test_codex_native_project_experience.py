from __future__ import annotations

import json

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

    session.request("Validate the browser checkout flow")
    session.approve_project_candidate("browser-testing")

    assert session.thread_id == original_thread_id
    assert session.started_nested_codex_processes == 0
    assert session.started_nested_codex_threads == 0
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

    session.request("Fix the intermittent login failure")

    assert session.loaded_skill_names == ("systematic-debugging",)
    assert "route-task" not in session.internal_commands
    assert session.started_nested_codex_processes == 0
    assert session.started_nested_codex_threads == 0


def test_approved_hook_governance_preserves_native_skill_behavior(
    native_project: CodexNativeProjectFixture,
) -> None:
    native_project.initialize(selected_skill="systematic-debugging")
    assert not (native_project.root / ".codex/hooks.json").exists()

    rendered = native_project.install_approved_hook()
    session = native_project.start_session()
    session.request("Fix the intermittent login failure")

    hooks = json.loads(
        (native_project.root / ".codex/hooks.json").read_text(encoding="utf-8")
    )
    assert hooks == rendered.hooks
    assert rendered.trust_digest == native_project.installed_hook_trust_digest()
    assert session.loaded_skill_names == ("systematic-debugging",)
    assert session.started_nested_codex_processes == 0
    assert session.started_nested_codex_threads == 0
