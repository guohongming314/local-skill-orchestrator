# Local Skill Orchestrator Design

**Date:** 2026-07-11  
**Status:** 已于 2026-07-13 被新设计替代
**Repository:** `local-skill-orchestrator`

> 本设计已被 `2026-07-13-project-ai-capability-bootstrapper-design.md`
> 替代。原有的运行时 Skill 路由思路仅作为历史背景保留，产品方向已经调整为
> 项目初始化、能力解析和持续治理。

## Purpose

Create a public, reusable Codex Skill that selects and sequences the smallest sufficient set of locally available Skills for a user request. It must resolve overlap across plugins, respect repository instructions and runtime availability, and explain its routing decisions without turning every task into a heavyweight workflow.

## Audience

- Individual Codex users with multiple local Skills installed.
- Skill authors testing trigger quality and interoperability.
- Contributors who want to run repeatable routing evaluations and report results.

## Scope

The first release is a lightweight, documentation-driven Skill. It will:

1. Infer the user's primary intent and execution scope.
2. Inspect the Skills exposed in the current session rather than assuming availability.
3. Apply instruction precedence: system/developer, user, repository instructions, explicitly requested Skills, specialized Skills, then generic workflow Skills.
4. Classify candidates as competing alternatives, complementary capabilities, sequential stages, unavailable, or deferred.
5. Check runtime and tool viability before selection.
6. Select the smallest sufficient Skill set and order it by task phase.
7. Avoid self-selection and recursive orchestration.
8. Keep obvious routing announcements concise and provide detailed explanations only when ambiguity exists or the user requests them.

The first release will not add an MCP server, background daemon, or automatic filesystem-wide Skill indexer. Those may be considered after external validation demonstrates a need.

## Repository Structure

```text
local-skill-orchestrator/
├── .github/workflows/validate.yml
├── docs/superpowers/specs/
├── local-skill-orchestrator/
│   ├── SKILL.md
│   └── agents/openai.yaml
├── tests/
│   ├── scenarios.md
│   └── results-template.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── .gitignore
```

## Routing Model

### Inputs

- User intent: explain, explore, design, plan, implement, debug, verify, review, release, or Skill management.
- Execution scope: read-only, plan-only, code modification, or full workflow.
- Explicit constraints: requested/forbidden Skills, file modification permission, subagent permission, network requirements, and required tools.
- Environment constraints: installed Skills, available tools/MCP servers, configured runtimes, and repository instructions.

### Decision Process

1. Parse intent, scope, and constraints.
2. Collect viable candidate Skills from the current environment.
3. Apply instruction precedence.
4. Remove unavailable or conflicting candidates.
5. Classify remaining candidates by relationship.
6. Select the smallest sufficient set.
7. Order selected Skills as understand → investigate → design → plan → implement → verify → review → integrate.
8. Announce the route proportionally to ambiguity.

### Conflict Rules

- Repository-mandated tools beat generic alternatives.
- Explicit user selection wins unless it violates higher-priority instructions or cannot run.
- A viable Skill beats a similar Skill with an unavailable runtime.
- Read-only requests cannot trigger implementation actions.
- Matching is not sufficient reason to invoke every Skill.
- Debugging identifies root cause before TDD implements a fix.
- Verification is required before claiming implementation success.
- The orchestrator must never select itself after orchestration begins.

## External Validation

The repository is intended for use by other people. Validation must be reproducible and distinguish baseline behavior from behavior with the Skill enabled.

Initial scenario groups:

1. Overlapping planning Skills with one runtime unavailable.
2. A trivial change that tempts excessive workflow selection.
3. A read-only debugging request that must not modify code.
4. A repository instruction that mandates CodeGraph over generic search.
5. A request that could cause recursive self-selection.
6. A complex task requiring a sequence of complementary Skills.
7. An explicitly requested Skill that conflicts with runtime availability.

Each scenario records:

- Environment and available Skill list.
- Exact user prompt.
- Baseline response without this Skill.
- Response with this Skill enabled.
- Selected and rejected Skills.
- Rule violations and reviewer notes.
- Pass/fail result.

Contributors should submit raw outputs rather than only conclusions. No production systems or credentials are required for validation.

## Distribution

The repository will be public on GitHub under the MIT License. The README will document manual installation by copying the Skill directory and will leave room for a future installer command after compatibility is verified. The Git remote will use GitHub only; no GitLab remote will be configured.

## Continuous Integration

GitHub Actions will perform deterministic checks that do not require model access:

- Validate required files and directory names.
- Validate YAML frontmatter and `agents/openai.yaml` syntax.
- Check Markdown links where practical.
- Ensure the Skill name matches its folder.

Behavioral evaluation remains a documented human/agent test process in the first release because model-dependent assertions are nondeterministic.

## Success Criteria

- A user can install the Skill from the public repository using documented steps.
- The Skill selects a minimal, ordered workflow in all initial scenarios.
- It does not recursively select itself.
- It respects read-only constraints and repository tool mandates.
- It reports unavailable runtimes instead of pretending a Skill can run.
- External testers can reproduce scenarios and submit comparable results.
- GitHub CI validates repository structure and metadata on every push and pull request.

## Future Options

Only after external results justify them:

- A script that inventories local Skill metadata.
- Machine-readable scenario fixtures and scoring.
- Compatibility adapters for additional agent runtimes.
- Packaging as a complete Codex plugin.
