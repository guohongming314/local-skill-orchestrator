from __future__ import annotations

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from tests.materialize.test_templates import inputs
from vibe.cli import app
from vibe.materialize.capability_manager import (
    render_agents_guidance,
    render_capability_manager_references,
    render_capability_manager_skill,
)
from vibe.models.resolution import CapabilityResolution, ResolutionStatus


def test_skill_is_narrow_capability_governance_not_a_task_router() -> None:
    blueprint, _, _ = inputs()
    document = render_capability_manager_skill(blueprint)
    frontmatter = document.split("---", 2)[1]

    for phrase in (
        "missing or unhealthy capability or dependency",
        "install, replace, update, remove, or manage",
        "Do not use for ordinary task classification",
        "existing capabilities are sufficient",
    ):
        assert phrase in frontmatter

    for phrase in (
        "cannot complete a task with the current skills or tools",
        "missing or unhealthy",
        "asks to manage capabilities",
        "Do not use this Skill for ordinary task classification",
        "Codex-native Skill discovery",
        "explain the capability gap",
        "approval",
        "install, replace, update, disable, or remove",
        "Doctor",
        "Never start another Codex",
        "never delegate task execution to `vibe run`",
    ):
        assert phrase in document
    assert "project-development" not in document


def test_references_capture_approved_providers_gaps_and_governance() -> None:
    _, plan, inventory = inputs()
    references = render_capability_manager_references(plan, inventory)

    assert set(references) == {
        "references/capability-gaps.md",
        "references/governance-commands.md",
        "references/quality-and-governance.md",
    }
    gaps = references["references/capability-gaps.md"]
    assert "`cli.pytest`" in gaps
    assert "release-automation" in gaps
    governance = references["references/quality-and-governance.md"]
    assert "explicit approval" in governance
    assert "Doctor" in governance


def test_governance_commands_are_exact_internal_codex_workflows() -> None:
    _, plan, inventory = inputs()
    document = render_capability_manager_references(plan, inventory)[
        "references/governance-commands.md"
    ]

    for command in (
        "vibe doctor --path <root> --json",
        "vibe capabilities list --config <codex-config> --plugins-root <plugins-root> "
        "--project <root> --user-skills <user-skills> --json",
        "vibe install <name> --path <root> --candidate-file <bundle> --approve",
        "vibe update <name> --path <root> --candidate-file <bundle> --approve",
        "vibe uninstall <name> --path <root>",
        "vibe reconcile --path <root> --dry-run",
        "vibe reconcile --path <root>",
    ):
        assert f"`{command}`" in document
    assert "L3" in document
    assert "item-specific approval" in document
    assert "Internal Codex operations" in document
    assert "Never ask the user to run" in document
    assert "Never start another Codex" in document
    assert "preserve the current conversation" in document
    for project_file in (
        ".ai-project/capability-requirements.yaml",
        ".ai-project/capabilities.yaml",
        ".ai-project/capabilities.lock",
    ):
        assert project_file in document
    assert "active `CODEX_HOME`" in document
    assert "may omit `--user-skills`" in document


@pytest.mark.parametrize(
    ("command_path", "options"),
    (
        (("doctor",), ("--path", "--json")),
        (
            ("capabilities", "list"),
            ("--config", "--plugins-root", "--project", "--user-skills", "--json"),
        ),
        (("install",), ("--path", "--candidate-file", "--approve")),
        (("update",), ("--path", "--candidate-file", "--approve")),
        (("uninstall",), ("--path",)),
        (("reconcile",), ("--path", "--dry-run")),
    ),
)
def test_each_documented_governance_command_uses_options_from_cli_help(
    command_path: tuple[str, ...], options: tuple[str, ...]
) -> None:
    result = CliRunner().invoke(app, [*command_path, "--help"])

    assert result.exit_code == 0, result.output
    for option in options:
        assert option in result.output


def test_documented_internal_hook_policy_option_is_registered_on_init() -> None:
    root = get_command(app)
    init = root.commands["init"]

    assert any("--hook-policy-file" in parameter.opts for parameter in init.params)


def test_skill_requires_governance_commands_reference_for_management() -> None:
    blueprint, _, _ = inputs()
    document = render_capability_manager_skill(blueprint)

    assert "[deterministic governance commands](references/governance-commands.md)" in document


def test_references_render_a_selected_provider_only_once() -> None:
    _, plan, inventory = inputs()
    duplicate = CapabilityResolution(
        requirement="testing",
        status=ResolutionStatus.SELECTED,
        capability_id="cli.pytest",
        reason="same provider satisfies another requirement",
    )
    plan = plan.model_copy(update={"resolutions": (*plan.resolutions, duplicate)})

    references = render_capability_manager_references(plan, inventory)

    assert references["references/capability-gaps.md"].count("`cli.pytest`") == 1


def test_agents_guidance_is_concise_and_preserves_codex_ownership() -> None:
    guidance = render_agents_guidance()

    assert len(guidance.encode("utf-8")) < 2048
    assert "Codex-native Skill discovery" in guidance
    assert "missing, unhealthy, or explicitly managed" in guidance
    assert "every project operation" not in guidance
    assert "vibe run" not in guidance
