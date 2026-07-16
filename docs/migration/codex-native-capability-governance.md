# Migrating to Codex-native capability governance

Vibe now treats the active Codex conversation as the normal place for project work.
The `vibe run` and `vibe plan` commands remain available temporarily for compatibility
and diagnostics, but they are no longer the primary task entry points.

## Old flow

The previous workflow started outside Codex: users described work to `vibe run`, or
generated a workflow and Context Capsule with `vibe plan`, and Vibe selected capabilities
before handing phases to Codex. That made Vibe an external task runner and duplicated
decisions that Codex can make with the live conversation context.

## Conversation-native flow

Start or continue the project task in the current Codex conversation. Codex reads the
project's installed Skills and governance files, selects the relevant Skills for the
current request, and performs the work without requiring a separate `vibe plan` or
`vibe run` step. Use Vibe to bootstrap, inspect, and govern those project-local
capabilities rather than to wrap routine Codex execution.

Codex owns Skill selection because it has the current request, conversation history,
workspace state, and Skill trigger instructions at the moment a decision is needed.
Keeping selection there avoids stale external plans and preserves the native Skill
workflow, including user-visible activation and any Skill-specific gates.

## Missing capabilities

When Codex cannot find an appropriate installed Skill, use the capability manager to
inspect available capabilities and install or reconcile the missing project-local
capability. Then continue the same Codex conversation so the newly available Skill can
be selected with the existing task context.

## Remaining CLI uses

`vibe plan` remains useful for compatibility integrations, deterministic plan or Context
Capsule inspection, CI assertions, and diagnostics. `vibe run` remains available for
existing automated integrations that still depend on the external phase-gated runner.
Both commands emit a deprecation warning on stderr; JSON stdout remains machine-readable.

## Compatibility period and removal criteria

The commands will remain during a compatibility period while supported integrations
migrate. Removal should happen only after conversation-native bootstrap and capability
management cover normal project work, CI and diagnostic replacements are documented,
and known consumers no longer rely on external plan or run behavior. A future release
must announce the removal window and any replacement interfaces before deleting either
command.
