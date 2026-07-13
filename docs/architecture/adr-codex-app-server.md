# ADR: Codex app-server structured-output protocol

- Status: Accepted
- Date: 2026-07-14
- Issue: #22

## Context

The control plane needs recoverable Codex threads and schema-valid final results. The app-server protocol is JSONL over stdio and its messages intentionally omit a `"jsonrpc": "2.0"` member. A transport success does not guarantee that an agent message is valid JSON or conforms to the caller's Pydantic contract.

Graph Run IDs belong to this project and must never be conflated with Codex Thread IDs. Runs also need an auditable turn lifecycle without persisting prompts, model output, commands, credentials, or other secret-bearing payloads.

## Decision

1. `JsonRpcSubprocessClient` owns the app-server subprocess, stdio routing, bounded timeouts, and shutdown/reaping.
2. Every app-server session performs `initialize` followed by the `initialized` notification before thread operations.
3. The project persists Graph Run ID and Codex Thread ID separately. Completed turns are represented by redacted audit events containing only IDs and terminal status.
4. `turn/start` receives `outputSchema` when a structured result is requested. The final completed `agentMessage` is validated with the caller's Pydantic model.
5. A validation failure permits exactly one repair turn on the same Codex thread. This preserves context while placing a strict bound on retries.
6. If repair also fails, an isolated `codex exec --json --output-schema ... --output-last-message ... --ephemeral` process is used. The schema and final-message files live in a temporary directory and are removed after validation.
7. Non-zero fallback exit, missing output, or invalid fallback JSON raises a typed, actionable error. Stderr is bounded before inclusion in diagnostics.
8. Approval requests remain deny-by-default under the policy adapter introduced by #21.
9. Persistence and diagnostics must not include raw prompts, model output, command arguments, environment secrets, or approval payloads.

## Consequences

The normal path retains thread continuity and requires only two turns. Malformed output gets one deterministic repair opportunity, while the separate exec path provides a schema-constrained recovery boundary. The fallback costs an additional process and loses app-server thread context, but it is invoked only after the bounded primary path fails.
