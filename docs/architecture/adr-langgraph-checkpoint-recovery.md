# ADR: LangGraph SQLite checkpoint recovery boundary

- **Status:** Accepted
- **Date:** 2026-07-14
- **Issue:** #53

## Context

The control plane needs to suspend a LangGraph workflow and recover it in a later
process without conflating LangGraph execution identity with the reusable Codex
conversation identity. Recovery must also stop when the repository inputs or the
approved permission state have changed since the pause.

## Decision

LangGraph's official `SqliteSaver` owns its checkpoint schema, serialization, and
connection lifecycle. Each command process opens the saver with
`SqliteSaver.from_conn_string(...)`, reconstructs the same compiled graph, invokes
it, and closes the connection before returning. The application does not copy or
migrate LangGraph's tables through Alembic.

The business database remains authoritative for control-plane state. It stores:

- the Graph Run ID and lifecycle status;
- the checkpoint namespace;
- the repository and resume-input digests;
- the permission-state digest; and
- the association from Graph Run ID to Codex Thread ID.

The Graph Run ID is passed to LangGraph as `configurable.thread_id`. The stable
checkpoint namespace is passed separately as `configurable.checkpoint_ns`. The
Codex Thread ID is graph state and a business association, but is never reused as
the LangGraph thread ID. This preserves two independently recoverable identities.

Before a resume invokes LangGraph, the workflow requires a paused business run,
the supported namespace, an existing Codex thread association, an unchanged
repository digest, and an exactly unchanged permission-state digest. Any digest
change rejects direct resume while leaving the run paused. The caller must restart
or obtain a new approval rather than silently accepting stale authority.

The reusable `CheckpointSpike` service and the CLI's `checkpoint-start` and
`checkpoint-resume` commands provide the integration boundary for later workflow
work. The cross-process test fixture invokes separate Python processes against the
same business and checkpoint databases.

## Persistence and data handling

Checkpoint state is intentionally minimal: controlled identifiers, status, and the
interrupt response. Business persistence contains only digests and identifiers.
Prompts, model output, credentials, tokens, and repository contents are outside
this spike's persisted state.

## Consequences

- LangGraph upgrades, not application migrations, govern checkpoint tables.
- Recovery can occur in a fresh process by reopening the same checkpoint database
  with the same Graph Run ID and namespace.
- Business lifecycle queries remain independent of LangGraph internals.
- Stale repository or permission state fails closed and remains recoverable through
  an explicit restart/reapproval flow.
- SQLite is the accepted local spike backend; production scaling or remote
  checkpoint storage is a later decision.
