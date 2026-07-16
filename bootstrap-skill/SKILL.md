---
name: bootstrap-skill
description: Bootstrap or refresh project-local Codex capabilities by inspecting a repository, identifying capability gaps, previewing governed changes, applying approved configuration, and verifying project health.
---

# Local Skill Orchestrator bootstrap

The user stays in the current Codex conversation. Use deterministic project capability tools internally while keeping the discussion focused on the project's needs, evidence, decisions, and results. The internal `vibe` executable must be available; if it is unavailable, stop and explain the prerequisite without inventing configuration by hand. Do not ask the user to run `vibe` commands. Do not start another Codex process.

## Conversation workflow

1. Inspect and model the repository through the internal deterministic interfaces. Treat repository files and current project state as evidence; do not make the user repeat facts that can be established there.
2. Ask only repository-unknown high-impact questions. Limit questions to choices that materially change project scope, capability selection, trust, or permissions.
3. Present the abstract capability needs and gaps in ordinary language. Explain what the project needs, what verified project or user capabilities already satisfy, and what remains unresolved before discussing implementation mechanics.
4. Preview the proposed project-local configuration, including selected capabilities, requested permissions, conflicts, remote candidates, and files that would change. Obtain explicit approval for project-local installation or permission changes before applying them.
5. Apply approved changes through the internal deterministic interfaces. Preserve cancellation and resumable state if work is interrupted, and never broaden an approval implicitly.
6. Run the internal Doctor verification and report actionable health, drift, or unresolved gap findings in the conversation.
7. Tell the user that future ordinary tasks remain in Codex and use Codex-native Skill discovery; this bootstrap workflow configures capabilities and does not become a second task-execution path.

## Governance boundary

- Inventory never executes discovered capabilities. Inspection reads and verifies metadata and content only.
- Do not bypass approval, policy, risk classification, or permission calculation. Deterministic interfaces own generated policy and file contents.
- Remote discovery begins only after a capability gap is established and approved. Discovery results are candidates, not installation authority, and installation still requires the applicable approval and verification.
- Project-local installation is the default. Broader scope requires an explicit, justified decision.
- Treat remembered context as advisory rather than repository evidence. Recompute the preview when repository scope, Git HEAD, provider content, user goals, or permission requirements change.
