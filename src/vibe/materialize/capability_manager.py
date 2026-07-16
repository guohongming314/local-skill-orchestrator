"""Render the narrow project capability-governance Skill."""

from __future__ import annotations

from vibe.inventory.service import InventoryResult
from vibe.models.blueprint import Blueprint
from vibe.models.resolution import ResolutionPlan, ResolutionStatus


def render_capability_manager_skill(blueprint: Blueprint) -> str:
    """Render guidance that activates only for capability governance."""
    description = (
        "Use for a missing or unhealthy capability or dependency, or when the user asks "
        "to install, replace, update, remove, or manage capabilities. Do not use for "
        "ordinary task classification or when existing capabilities are sufficient."
    )
    return f"""---
name: project-capability-manager
description: {description}
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
3. Read the [deterministic governance commands](references/governance-commands.md).
4. Diagnose and explain the capability gap or unhealthy dependency.
5. Recommend the smallest suitable change and obtain approval before mutation.
6. As approved, install, replace, update, disable, or remove the capability.
7. Run Doctor and focused verification after changes.

Never start another Codex, and never delegate task execution to `vibe run`.
"""


def render_capability_manager_references(
    plan: ResolutionPlan, inventory: InventoryResult
) -> dict[str, str]:
    """Render local, deterministic capability context and governance references."""
    manifests = {item.manifest.capability_id: item.manifest for item in inventory.capabilities}
    selected_ids = sorted(
        {
            resolution.capability_id
            for resolution in plan.resolutions
            if resolution.status is ResolutionStatus.SELECTED
            and resolution.capability_id is not None
        }
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
    commands = """# Deterministic governance commands

These are Internal Codex operations. Never ask the user to run them. Never start another Codex;
do not start another process or thread, and preserve the current conversation throughout.
Use the command tool available in the current conversation with the exact argument
contracts below.

## Inspect current capabilities and gaps

1. Run `vibe inspect --path <root> --json` for repository facts.
2. Run `vibe capabilities list --path <root>` for normalized local providers.
3. Read `.ai-project/capability-requirements.yaml`, `.ai-project/decisions.md`, and
   `references/capability-gaps.md` to identify the smallest unresolved gap.

## Review candidate evidence

Before mutation, inspect the candidate bundle at `<bundle>` and verify its identity,
source, digest, permissions, compatibility, risk level, and evidence. Explain the
specific proposed change and obtain approval in the current conversation.

## Approved project-local install

After approval, run
`vibe install <name> --path <root> --candidate-file <bundle> --approve`.
The `--approve` flag covers only an approved L1/L2 install. For an L3 bundle, obtain
item-specific approval for every L3 capability or permission boundary before invoking
the install; one broad approval must never be reused for multiple L3 items.

## Doctor

After every mutation, run `vibe doctor --path <root> --json` and focused verification.

## Update

Review the replacement bundle and permission delta, obtain fresh approval, then run
`vibe update <name> --path <root> --candidate-file <bundle> --approve`. Permission
expansion and every L3 item require their own explicit approval boundary.

## Uninstall

Explain the recorded transaction being reversed, obtain approval, then run
`vibe uninstall <name> --path <root>`. Follow with Doctor and focused verification.

## Reconcile

Run `vibe reconcile --path <root> --dry-run` first. Explain each proposed drift
resolution and obtain approval before running `vibe reconcile --path <root>` to apply
the approved reconciliation.

## Approved Hook policy boundary

For optional project Hook governance, create a strict `ProjectHookPolicy` JSON or YAML
file only after item-specific user approval, including non-empty
`approval_provenance`. Pass that internal artifact to init with
`--hook-policy-file <policy-file>`. Never infer approval or coerce an unapproved policy.
"""
    return {
        "references/capability-gaps.md": gaps_document,
        "references/governance-commands.md": commands,
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
