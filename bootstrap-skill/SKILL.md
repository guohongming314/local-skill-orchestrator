---
name: bootstrap-skill
description: Bootstrap or refresh project-local AI development configuration with local-skill-orchestrator. Use when Codex needs to inspect a repository, discover verified local capabilities, preview and apply `vibe init`, diagnose configuration drift, or explain the boundary between Skill guidance and deterministic CLI policy.
---

# Local Skill Orchestrator bootstrap

Use the Skill as procedural guidance. The CLI owns deterministic inventory, risk classification, capability resolution, permission calculation, rendering, and change application.

## Workflow

1. Confirm the `vibe` command is available. If it is missing, stop and explain how to install the Python package; do not invent project configuration by hand.
2. Run `vibe inspect --path <project>` and summarize repository evidence and diagnostics.
3. Run `vibe init --dry-run --path <project>` and review decisions, requested permissions, gaps, conflicts, and proposed files.
4. Obtain the approval required by the CLI. Do not bypass approval, rewrite generated policy, or treat memory as authoritative evidence.
5. Run `vibe init --path <project>` only after approval. Preserve cancellation and resume state if execution is interrupted.
6. Run `vibe doctor --path <project>` and report actionable health or drift findings.

## Safety boundary

- Let the CLI own deterministic policy and generated file contents.
- Use this Skill only to sequence commands, explain evidence, and request decisions.
- Do not bypass approval or broaden permissions to make resolution succeed.
- Do not execute discovered Skills, MCP servers, or commands during inventory.
- Prefer a new dry run when repository scope, Git HEAD, phase, provider content, or user goals change.
