# Trusted Multi-Source Remote Discovery Design

**Date:** 2026-07-22  
**Status:** User-approved design pending written-spec review  
**Product surface:** Codex-native Bootstrap Skill and deterministic `vibe` capability tools

## Problem

Initialization currently treats `--remote-discovery` as permission to read a prebuilt
`.ai-project/remote-candidates.json` snapshot. It does not query a live source. When the
snapshot is absent, the command returns an empty candidate set, and the surrounding Codex
conversation can incorrectly report that remote discovery found no verified candidates.

This conflates materially different states:

- the user has not approved discovery;
- no discovery source is configured;
- a source is unavailable or rate-limited;
- a search completed with no results;
- results existed but all failed policy checks;
- verified candidates are available but installation was not approved.

The product must perform real discovery only after a confirmed local capability gap and
explicit discovery approval. Discovery approval must never imply installation approval.

## Goals

1. Search trusted remote sources after an explicit local capability gap and user approval.
2. Support the official MCP Registry, skills.sh, GitHub, and configured organization registries.
3. Preserve local-first resolution and static candidate leads when network discovery is not run.
4. Normalize, deduplicate, verify, filter, rank, and explain candidates deterministically.
5. Use community popularity as a ranking signal without allowing popularity to bypass security.
6. Show at most three default recommendations per capability gap, with additional eligible
   candidates available on request.
7. Preserve project-local installation, immutable identity, explicit permission review,
   transactionality, rollback, audit, and Doctor verification.

## Non-goals

- Automatically installing any remote capability.
- Treating GitHub stars, skills.sh adoption, or MCP Registry presence as proof of safety.
- Searching before a local gap exists or before the user approves network discovery.
- Running discovered capability code during inventory or search.
- Building a general web search engine.
- Replacing Codex-native Skill selection for ordinary project tasks.

## User experience

The Bootstrap Skill follows this sequence:

```text
inspect repository and local Codex environment
→ derive abstract capability requirements
→ resolve verified local providers
→ identify genuine gaps
→ show static candidate directions and their unverified status
→ ask whether trusted remote discovery may access the network
→ search approved sources
→ normalize, deduplicate, verify metadata, and apply policy filters
→ rank and show the top three candidates per gap
→ let the user inspect, replace, reject, defer, or select a candidate
→ preview exact installation permissions and file changes
→ obtain separate installation approval
→ install project-locally, verify, lock, audit, and run Doctor
```

Before discovery, the conversation may say:

> Browser validation is still missing. Local candidate directions include Playwright and
> Chrome DevTools MCP, but no remote source has been queried or verified yet. May I search
> the approved remote sources for project-local candidates?

It must not say that discovery returned no verified candidates unless at least one source was
actually queried successfully.

## Architecture

### Discovery service

Introduce a deterministic discovery service that accepts:

- abstract capability gaps;
- the repository snapshot and Blueprint;
- approved source configuration;
- organization policy;
- offline/cache policy;
- per-source time and result limits.

The service invokes source adapters, normalizes their records into `RemoteCandidate`, attaches
source-specific evidence, deduplicates cross-listed projects, applies hard policy filters, and
returns a structured `DiscoveryReport`.

The service does not install artifacts and does not execute discovered code.

### Source adapters

All source adapters implement the existing `RegistrySource`-style search/fetch boundary while
returning source diagnostics alongside candidates.

Initial adapters:

1. **MCP Registry** — official MCP server metadata using the existing Registry client.
2. **skills.sh** — Skill catalog metadata, adoption signals, canonical source repository,
   version or commit identity, and declared installation form.
3. **GitHub** — repository search and metadata for candidate Skills, Plugins, MCP servers, and
   CLI tools. GitHub discovery uses authenticated access when available and read-only anonymous
   access otherwise.
4. **Organization Registry** — explicitly configured internal or approved catalogs using the
   normalized source interface.

Source failures are isolated. One failed source does not erase successful results from another.

### Snapshot and cache boundary

`.ai-project/remote-candidates.json` becomes an output cache and reproducibility snapshot, not
the discovery implementation. The file records:

- query capability and source;
- retrieval timestamp and cache status;
- normalized candidate metadata;
- immutable source identifiers where available;
- ranking evidence;
- source diagnostics;
- policy-filter summaries without secret content.

Offline initialization may reuse a non-expired snapshot and must identify the result as cached.
An absent snapshot is `not-requested` or `source-unavailable`, never `no-results` by itself.

## Discovery states

Each capability gap has one explicit discovery state:

- `not-requested`: the user has not approved remote discovery;
- `source-unavailable`: no approved source is configured or reachable;
- `search-failed`: every attempted source failed;
- `no-results`: at least one source completed successfully and returned no matching records;
- `all-filtered`: matching records existed but all failed hard policy or safety checks;
- `candidates-found`: at least one eligible candidate can be shown;
- `installation-deferred`: the user retained the gap for later;
- `installation-rejected`: the user rejected available candidates for the project scope.

The report also contains per-source outcomes so partial success and rate limiting remain visible.

## Candidate normalization and deduplication

Candidates from different sources are merged only when immutable or high-confidence identity
matches, in this order:

1. identical canonical repository and commit or release digest;
2. identical package identifier and version plus matching digest;
3. explicit cross-source canonical reference.

Names alone never cause merging. Conflicting digests or publishers remain separate and receive
a supply-chain conflict finding.

The merged candidate preserves all source references and uses the strongest verified evidence
without discarding weaker or conflicting evidence.

## Hard filters

A candidate cannot enter the default recommendation list when any of these conditions holds:

- the source or artifact location cannot be established;
- the selected artifact cannot be pinned to a version, commit, or verified digest before install;
- repository or package identity conflicts across sources;
- the repository is archived without an approved maintained successor;
- static scanning detects instruction injection or security-control bypass content;
- requested access includes unrelated secrets, unauthorized project-external writes, or an
  L4 permission classification;
- declared and observed package behavior materially differ;
- permissions exceed the Blueprint or organization-policy ceiling;
- the publisher, source, or capability is blocked by organization policy;
- the advertised capability is not supported by inspected metadata or content.

Candidates may be discovered before a final artifact digest is available, but they must be
clearly marked `metadata-only` and cannot be approved for installation until fetch-time digest,
publisher, permission, and static-scan verification succeeds.

## Ranking

Eligible candidates receive five separately reported scores:

| Dimension | Weight | Evidence |
| --- | ---: | --- |
| Fit | 35 | capability match, project facts, platform/runtime compatibility |
| Trust | 25 | source tier, publisher verification, immutable identity, cross-source agreement |
| Risk | 20 | permission level, static scan, external writes, credentials, executable content |
| Maintenance | 10 | recent releases/commits, archival state, issue responsiveness, contributors |
| Popularity | 10 | GitHub stars/forks/dependents and skills.sh/MCP adoption signals |

Risk is converted to a safety contribution only after hard filtering; lower residual risk ranks
higher. Raw source metrics are normalized logarithmically and bounded, preventing very large
projects from overwhelming fit and trust.

Popularity cannot:

- override a hard filter;
- compensate for unverifiable executable content;
- raise a candidate above the project permission ceiling;
- convert a metadata-only candidate into an installable candidate.

GitHub candidates enter the default shortlist only when they satisfy at least one discovery
confidence condition:

- official or verified publisher ownership;
- cross-listing by an approved Registry;
- configured organization approval;
- sufficient bounded popularity and maintenance evidence.

Low-popularity but high-fit candidates remain available as secondary results when they pass all
safety filters. They do not appear in the default top three unless fewer qualified candidates
exist and their lower confidence is made explicit.

## Approval boundaries

There are two separate approvals:

1. **Discovery approval** authorizes read-only network access to named sources for the current
   project initialization or current gap review.
2. **Installation approval** authorizes one exact candidate, immutable revision, permission set,
   and project-local ChangeSet.

Discovery approval does not authorize fetching executable artifacts for preflight unless the
user requests candidate details. Candidate-detail fetch remains read-only and must be disclosed.
Installation approval is invalidated by version, digest, publisher, permission, or file-diff
changes.

## Error handling and degradation

- A source timeout, authentication failure, or rate limit produces a source diagnostic and does
  not discard candidates from successful sources.
- If every source fails, the gap state is `search-failed`, not `no-results`.
- If no approved source exists, the state is `source-unavailable`.
- If one source succeeds with zero results while another fails, the overall state is
  `no-results` with a partial-failure warning.
- If all candidates fail policy, the state is `all-filtered` and the report summarizes filter
  categories without exposing malicious content or credentials.
- Static local candidate directions remain visible in every non-success state and are labeled
  as unverified leads.
- Initialization may continue with unresolved gaps after explicit user deferral; required gaps
  must be reflected in generated configuration and Doctor findings.

## Bootstrap Skill behavior

The Bootstrap Skill must:

- distinguish static leads from remotely verified candidates;
- ask for discovery approval after showing the confirmed gaps;
- name the sources and network scope being requested;
- invoke deterministic discovery rather than infer search results itself;
- present source status, ranking explanations, permissions, and alternatives;
- never equate missing cache data with an empty successful search;
- obtain a separate approval before any installation or permission change;
- preserve the current Codex conversation and never launch a nested Codex task.

## Testing and acceptance

Unit coverage must include:

- source normalization for MCP Registry, skills.sh, GitHub, and organization registries;
- source-specific pagination, rate limits, cache behavior, and malformed responses;
- cross-source deduplication and digest conflicts;
- hard filters and organization policy;
- logarithmic popularity normalization and bounded score contribution;
- stable deterministic ordering for equal scores;
- every discovery state and partial-source outcome.

End-to-end coverage must include:

- no local provider, discovery not approved, and zero network requests;
- discovery approved with real adapter fixture responses and ranked candidates;
- GitHub and skills.sh duplicates merged correctly;
- a highly popular candidate rejected by a hard safety filter;
- a less popular but substantially better-fit candidate ranked first;
- one source rate-limited while other source results remain usable;
- all sources unavailable with static leads retained;
- separate discovery and installation approvals;
- candidate mutation between review and install invalidating approval;
- project-local install, lock, Doctor, uninstall, and rollback round trip.

Release acceptance requires an attended Codex initialization demonstrating that the conversation
asks before discovery, shows ranked multi-source candidates, asks separately before installation,
and accurately reports source failures or empty results.

## Migration

Existing fixture snapshots remain supported as cached discovery inputs. Tests that currently
describe snapshot loading as remote discovery must be renamed or extended so they do not claim
live-source coverage. The existing MCP `RegistryClient`, scoring, provenance, scanning, install,
audit, and rollback components should be reused rather than replaced.

The initial implementation should not remove `--remote-discovery`; it should redefine the option
as approval to run the configured discovery service. An explicit offline/cache-only option will
retain deterministic fixture and CI behavior.
