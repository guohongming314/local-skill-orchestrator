"""Render the narrow project capability-governance Skill."""

from __future__ import annotations

from vibe.inventory.service import InventoryResult
from vibe.models.blueprint import Blueprint
from vibe.models.resolution import ResolutionPlan, ResolutionStatus


def render_capability_manager_skill(blueprint: Blueprint) -> str:
    """Render guidance that activates only for capability governance."""
    return f"""---
name: project-capability-manager
description: Diagnose and govern missing or unhealthy capabilities for {blueprint.project_name}.
version: 1.0.0
---

# Project capability manager

Use this Skill only when Codex cannot complete a task with the current skills or tools,
a required dependency is missing or unhealthy, or the user asks to manage capabilities.

Do not use this Skill for ordinary task classification or when existing capabilities suffice.
Use Codex-native Skill discovery for ordinary tasks.

When capability governance is needed:

1. Read [approved providers and capability gaps](references/capability-gaps.md).
2. Read the [quality and governance rules](references/quality-and-governance.md).
3. Diagnose and explain the capability gap or unhealthy dependency.
4. Recommend the smallest suitable change and obtain approval before mutation.
5. As approved, install, replace, update, disable, or remove the capability.
6. Run Doctor and focused verification after changes.

Never start another Codex, and never delegate task execution to `vibe run`.
"""


def render_capability_manager_references(
    plan: ResolutionPlan, inventory: InventoryResult
) -> dict[str, str]:
    """Render local, deterministic capability context and governance references."""
    manifests = {item.manifest.capability_id: item.manifest for item in inventory.capabilities}
    selected_ids = sorted(
        resolution.capability_id
        for resolution in plan.resolutions
        if resolution.status is ResolutionStatus.SELECTED
        and resolution.capability_id is not None
    )
    lines = ["# Approved providers and capability gaps", "", "## Approved providers"]
    if selected_ids:
        lines.extend(
            f"- `{identifier}`: {', '.join(sorted(manifests[identifier].provides))}"
            for identifier in selected_ids
        )
    else:
        lines.append("- None selected.")
    gaps = sorted(
        resolution.requirement
        for resolution in plan.resolutions
        if resolution.status is ResolutionStatus.GAP
    )
    lines.extend(["", "## Capability gaps"])
    lines.extend(f"- {gap}" for gap in gaps) if gaps else lines.append("- None.")
    gaps_document = "\n".join(lines) + "\n"
    governance = """# Quality and governance

- Explain the capability gap and why current capabilities do not suffice.
- Prefer approved, least-privilege providers and the smallest reversible change.
- Obtain explicit approval before install, replace, update, disable, or remove actions.
- Preserve project-owned files and record deterministic capability state.
- Run Doctor and focused verification after every approved change.
"""
    return {
        "references/capability-gaps.md": gaps_document,
        "references/quality-and-governance.md": governance,
    }


def render_agents_guidance() -> str:
    """Render concise managed AGENTS.md guidance without routing ordinary work."""
    return (
        "## Project capability governance\n\n"
        "Use Codex-native Skill discovery for ordinary work. Use the\n"
        "`project-capability-manager` Skill only when a needed capability is "
        "missing, unhealthy, or explicitly managed by the user.\n"
    )
