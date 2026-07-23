# Default Read-Only Remote Discovery Design

## Goal

Make capability discovery usable without asking users to authorize searches or select
trusted search sources, while preserving strict approval boundaries for downloads,
installation, execution, and permission expansion.

## User Experience

`vibe init` searches supported built-in remote metadata sources by default whenever an
unresolved capability gap exists. Users are not asked to approve read-only discovery or
choose trusted sources. They may explicitly disable network discovery with
`--no-remote-discovery`, use `--remote-offline`, or be constrained by organization policy.

Source trust remains evidence used to filter and rank candidates. It is not permission to
perform a search. A discovered candidate is never installation authority.

## Authorization Boundary

Read-only metadata discovery is a system-recommended default, not a user approval. The
project decision model records discovery as enabled by the recommended default without
claiming that the user approved it. Artifact fetch, installation, update, execution,
candidate runtime network access, project writes, and permission expansion retain their
existing independent approval and policy gates.

Explicit user or organization denial overrides the default. Offline mode performs no
network access and may use only cached discovery responses.

## Sources And Selection

The orchestrator automatically queries all applicable built-in sources for each generated
query. Organization registries are included when configured. Users do not need to rank or
trust sources before search. Source tier, publisher identity, immutable revision, digest,
maintenance, declared permissions, and organization policy determine whether a result may
be shortlisted or installed.

## Result Semantics

Every source/query attempt produces a diagnostic containing source ID, query, status, and
an optional sanitized reason.

- A valid parsed response with zero matching records is `success` and can contribute to
  overall `no-results`.
- Empty output, malformed or unparseable output, a failed primary request followed by an
  empty or unparseable fallback, authentication failure, rate limiting, and transport
  failure are source failures.
- If no source/query attempt succeeds, the overall result is `search-failed`.
- If at least one attempt succeeds and produces no accepted candidate, existing
  `no-results`, `all-filtered`, and partial-failure semantics apply.
- No remote candidate is synthesized from a failed response.

Failure messages must be useful but must not expose response bodies, credentials, raw
prompts, command arguments, or environment secrets.

## Persistence And Recovery

Initialization stores the complete structured discovery reports in the existing durable
checkpoint. This is the initialization audit record for discovery: requirement, attempted
sources, per-query source diagnostics, statuses, counts, sanitized reasons, partial-failure
state, and verified remote candidates. A resumed run can therefore report the concrete
source failure instead of treating missing process output as an empty successful search.

Discovery diagnostics are refreshed when discovery is rerun and are never rewritten into
`no-results` merely because a resumed external search also produced no parseable output.

## Fallback Behavior

Remote discovery failure does not discard verified local capabilities or deterministic
static provider leads. The preview may continue with those results, labeling static leads
as unverified and non-installation-ready. Recommendation readiness must distinguish an
unresolved remote search failure from a genuine zero-result search, but it must not invent
remote evidence.

## Generated Guidance

The bootstrap Skill and generated project capability-manager guidance instruct Codex to
perform read-only discovery automatically. They must not ask users for discovery approval
or trusted-source selection. They continue to require exact, item-specific approval before
mutation and preserve all existing security checks.

## Compatibility

The CLI exposes paired `--remote-discovery/--no-remote-discovery` options with discovery
enabled by default. Existing explicit `--remote-discovery` calls continue to work. Stored
legacy `not-requested` discovery authorization values remain readable; on a new run they do
not disable the new default unless an explicit denial or opt-out exists.

## Verification

Tests cover default enablement, explicit opt-out, offline behavior, generated Skill text,
empty and malformed source responses, failed fallback/resume behavior, aggregate status,
checkpoint persistence, local/static fallback, and preservation of install approval gates.
The full test suite, Ruff, mypy, and package build must pass.

## Approval Record

The user approved this design in the Codex conversation on 2026-07-23 and requested a
complete implementation without intermediate questions.
