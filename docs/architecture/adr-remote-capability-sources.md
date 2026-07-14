# ADR: Remote capability sources and registry contract

- **Status:** Accepted
- **Date:** 2026-07-15
- **Issue:** #107
- **Parent epic:** #106

## Context

Remote discovery is allowed only after local resolution levels 1–6 leave an
explained capability gap. The design fixes the remaining trust order as:

7. official registries and marketplaces;
8. verified publishers;
9. community indexes; and
10. general source search.

A source can improve recall, but it cannot make mutable metadata immutable or
turn a package-registry account into a verified capability publisher. Discovery
therefore needs a small source contract which preserves provenance and separates
source trust from later publisher verification, policy filtering, scoring, static
analysis, approval, and installation.

This spike surveyed sources available on 2026-07-15. Rate limits and schemas are
operational observations, not permanent guarantees; clients must honor response
headers and fail closed when a source changes incompatibly.

## Survey

`Tier` below is the highest tier the source itself can justify. An item can be
demoted when its publisher identity is weaker. No source may promote an item to a
more trusted tier merely because the item is popular.

### MCP servers

| Candidate source | Tier | Metadata and identity signals | Version/digest immutability | Limits and offline behavior |
|---|---:|---|---|---|
| Official MCP Registry (`registry.modelcontextprotocol.io`) | 7 | Server name, description, repository, package/transport declarations, version records; registry namespace and validation are source signals, while publisher verification remains separate | Registry versions are snapshots, but installation must resolve the declared package or repository to its own immutable digest | Public HTTP API; treat quotas as server-controlled and honor `Retry-After`; cached snapshots remain usable offline until policy expiry |
| npm registry MCP packages | 8 only for a publisher verified by E12.3; otherwise 9 | Package metadata, maintainers, versions, deprecation, repository, download artifact URL and `dist.integrity` | Published version tarballs have integrity hashes; tags such as `latest` are mutable and must never be lock targets | Registry/CDN throttling is not a stable contract; npm cache can support offline reads only after an artifact was fetched |
| PyPI MCP distributions | 8 only for a verified publisher; otherwise 9 | Project/release metadata, owners exposed through PyPI UI, files, `requires_python`, yanked status, hashes, provenance attestations when present | Release file hashes are immutable lock evidence; project names, metadata, and release selection are mutable | JSON/Index APIs and CDN are network services with changeable limits; locally cached metadata/artifacts are required offline |
| Smithery catalog | 9 | Community catalog descriptions, deployment/configuration hints, repository links and popularity signals | Catalog entries are mutable; a repository commit plus artifact digest must be resolved independently | Network-only discovery; quota/API terms are provider-controlled; stale cache is advisory, never install authority |
| GitHub repository/code search | 10 (or 8 after independent publisher verification) | Repository owner, commit history, release tags, signatures, security and activity metadata | Commit SHA and release assets with recorded digests can be pinned; branches, tags and search results are mutable | Authenticated REST has explicit rate-limit headers; offline use is limited to cached responses and already fetched Git objects |

### Agent Skills

| Candidate source | Tier | Metadata and identity signals | Version/digest immutability | Limits and offline behavior |
|---|---:|---|---|---|
| OpenAI-maintained skills repositories/catalog entries | 7 for OpenAI-owned entries | GitHub organization identity, repository history, skill path and `SKILL.md`; repository ownership is the publisher signal | Pin the exact commit and compute a digest over the normalized skill directory; default branches are mutable | GitHub API limits apply; a cached tree/commit is fully inspectable offline |
| Anthropic `anthropics/skills` repository | 7 for Anthropic-owned entries | Official organization ownership, commit history, per-skill files and license | Pin a commit and normalized directory digest; branch heads are mutable | GitHub API limits apply; cached Git objects work offline |
| `skills.sh` index | 9 | Searchable skill records, source repository links and adoption/community signals | Index records and rankings are mutable; resolve to a repository commit and local content digest | Network service with provider-controlled limits; cached results are discovery hints only |
| Verified publisher GitHub repositories | 8 | Verified organization/domain relationship from E12.3, repository metadata, signed commits/releases when available | Exact commit plus normalized skill-directory digest | GitHub rate limits apply; cached commits remain usable offline under cache policy |
| General GitHub search/topics | 10 | Repository metadata and code contents, but no capability-specific curation | Only an exact commit and computed directory digest are immutable | Search requires network unless cached; results expire quickly and must not authorize installation |

### Plugins (`marketplace.json` feeds)

| Candidate source | Tier | Metadata and identity signals | Version/digest immutability | Limits and offline behavior |
|---|---:|---|---|---|
| Host-vendor official plugin marketplace | 7 | Vendor-curated marketplace identity, plugin name/description/version/source and host compatibility; for Claude Code this is a `.claude-plugin/marketplace.json` feed | Marketplace entries are mutable. Pin the referenced Git commit or release artifact and compute its digest | Delivery may use GitHub or vendor hosting; cache the signed/hashed feed snapshot and resolved artifacts for offline inspection |
| Marketplace feed in a verified publisher repository | 8 | Verified repository owner, feed history, plugin source, version and optional category/tags | Pin feed commit and each resolved plugin source; semantic versions and branches alone are insufficient | Hosting-specific limits (commonly GitHub); cached feed may be searched offline until expiry |
| Community-maintained `marketplace.json` feed | 9 | Maintainer/repository history and manifest metadata without authoritative publisher proof | Pin feed commit and plugin artifact digest; mutable URLs are rejected as lock targets | Network-dependent discovery; stale cache is advisory and cannot bypass revalidation for install |
| General GitHub search for `.claude-plugin/marketplace.json` | 10 | Repository/search metadata with no marketplace curation guarantee | Search result is mutable; exact commit and content digest required after selection | GitHub search limits apply; short-lived negative-result cache, offline cached-result browsing only |

### CLI tools

| Candidate source | Tier | Metadata and identity signals | Version/digest immutability | Limits and offline behavior |
|---|---:|---|---|---|
| Homebrew/core formula API | 7 as an official curated catalog | Formula/cask metadata, versions, URLs, bottle tags and SHA-256 values, license and deprecation/disable state; Homebrew review is a source signal | Bottle/source SHA-256 is lock evidence; formula aliases and current-version metadata are mutable | Public JSON API/CDN with provider-controlled limits; Homebrew downloads/cache can serve artifacts already fetched |
| npm registry | 8 for a verified tool publisher; otherwise 9 | Package versions, maintainers, executable `bin`, repository, deprecation and tarball integrity | Exact version plus `dist.integrity`; dist-tags and ranges are mutable | Network registry with changeable throttling; npm cache is usable only for previously fetched records/artifacts |
| PyPI | 8 for a verified tool publisher; otherwise 9 | Release files, hashes, metadata, yanked state, Python requirements and attestations when supplied | Exact release file plus SHA-256; version specifiers and project metadata are mutable | Network APIs/CDN; offline installation requires cached metadata and wheel/sdist |
| Homebrew third-party taps | 9, or 8 after publisher verification | Git repository owner/history and formula metadata | Pin tap commit and formula artifact SHA-256 | Git hosting limits apply; cloned tap and cached bottles support partial offline operation |
| GitHub Releases/general search | 10, or 8 after publisher verification | Repository owner, releases, signatures/attestations when present, activity and security metadata | Pin release asset by digest and source commit; release tags and asset URLs alone are not sufficient | GitHub API rate limits apply; cached metadata and assets are required offline |

## Decision

### `RegistrySource` contract

E12.2 will define a read-only adapter equivalent to the following language-neutral
contract. Names here are normative even if the eventual Python representation is
a protocol plus Pydantic models.

```text
RegistrySource
  source_id: SourceId
  trust_tier: 7 | 8 | 9 | 10
  capabilities: set[CapabilityKind]
  cache_policy: CachePolicy

  fetch(query, cursor?, validators?, deadline) -> FetchPage
  resolve(locator, validators?, deadline) -> ResolvedCandidate
```

#### Source identity

- `source_id` is a stable, lowercase reverse-DNS identifier owned by the adapter,
  for example `io.modelcontextprotocol.registry`, `com.github.repository`, or
  `org.npm.registry`. It never includes credentials, mirrors, query text, or a
  user-selected publisher.
- `trust_tier` describes the source route, not the candidate. Candidate trust may
  be demoted, and tier 8 requires E12.3 publisher verification.
- `capabilities` declares which of `mcp-server`, `agent-skill`, `plugin`, and
  `cli-tool` the adapter can return.

#### Fetch semantics

- `fetch` is read-only, deterministic for the same cached snapshot, paginated,
  bounded by a deadline, and cancellable. It returns candidates plus a source
  cursor, retrieval time, freshness state, and HTTP/cache validators when the
  transport supplies them.
- Adapters must preserve the source's raw locator and normalized provenance but
  must not execute manifests, follow install scripts, authenticate to a candidate,
  or infer publisher verification.
- Results include `source_id`, `source_tier`, `source_locator`, `kind`, display
  metadata, publisher claims, version claims, artifact locators, source-native
  integrity fields, and `observed_at`.
- A source schema change, malformed record, rate limit, timeout, or authentication
  failure is a typed per-source error. Aggregation may continue with lower tiers,
  but it must expose the degradation and must not silently reinterpret fields.
- Resolution queries tiers 7 through 10 in order. Lower tiers may add recall only
  after higher-tier results are exhausted or insufficient under explicit policy.

#### Resolve and digest rules

- `resolve` converts a mutable discovery record into a candidate with an exact
  version/revision and artifact set. It does not install the candidate.
- A lockable candidate must have both an immutable locator (package version plus
  artifact identity, or repository commit SHA) and a cryptographic content digest.
- Registry-provided SHA-256/SRI is retained as source evidence. E12.3 independently
  downloads in a quarantine/cache area, verifies available upstream integrity,
  and records the project's own SHA-256 over the exact bytes. Directory-based
  capabilities also receive a deterministic normalized-tree digest.
- Tags, branches, version ranges, dist-tags, search-result URLs, and marketplace
  feed positions are mutable references and are never written to
  `capabilities.lock` as the sole identity.
- If bytes previously observed for the same immutable locator change, resolution
  fails as a security event; it never refreshes the digest in place.

#### Cache policy and offline expectations

```text
CachePolicy
  metadata_ttl
  negative_ttl
  stale_if_error
  max_snapshot_age
  artifact_retention
  revalidate_before_install: true
```

- Cache keys include source id, adapter schema version, normalized query/locator,
  page cursor, and authentication scope without storing secret material.
- Successful metadata and negative results have separate TTLs. Conditional fetch
  uses ETag/Last-Modified when available. Rate-limit responses are not negative
  results and honor `Retry-After`/reset metadata.
- Offline discovery is cache-only and explicitly labels every result `fresh`,
  `stale`, or `expired`. Stale results may be explained and compared; expired
  results are historical evidence only.
- Offline installation is permitted only after explicit approval when the exact
  immutable artifact and digest are already cached and all required verification
  inputs are available. A stale catalog record alone can never authorize install.
- Cache misses, incomplete pagination, or unavailable provenance produce an
  honest partial/empty result. The client never falls through to live general
  search while operating in offline mode.
- Cache corruption or a digest mismatch fails closed and evicts/quarantines the
  affected object; it does not silently refetch during an offline operation.

### First two source adapters

1. **Official MCP Registry (`io.modelcontextprotocol.registry`, tier 7).** It is
   the highest-trust capability-specific remote source, has a public versioned API,
   and directly exercises package/transport normalization needed by later MCP work.
2. **GitHub repositories (`com.github.repository`, tier determined per route).**
   One adapter can resolve exact commits and normalized subdirectory digests for
   Agent Skills and plugin feeds, while also providing provenance for MCP servers
   and CLI release assets. Curated allowlisted repositories enter at tier 7 or 8;
   community indexes at tier 9 hand off their repository locators to this adapter;
   general GitHub search remains a distinct tier-10 route.

This pairing deliberately favors trustworthy provenance and immutable resolution
before breadth. npm, PyPI, Homebrew, and community-index adapters follow after the
shared caching and publisher-verification boundaries are proven.

## Rejected alternatives

- **Implement npm first:** broad recall, but package ownership alone does not prove
  capability publisher identity and would prematurely mix discovery with package
  installation semantics.
- **Implement a community index first:** useful for ranking and recall, but mutable
  catalog records cannot establish lock identity or publisher trust.
- **Use one numeric score for source and publisher trust:** hides why a candidate is
  trusted and permits popularity to compensate for weak provenance, contrary to
  the design.
- **Treat a semantic version or Git tag as immutable:** both can select different
  bytes through mutable metadata; exact artifacts and digests are required.
- **Require live network access for all reads:** prevents reproducible explanation
  and review. Conversely, allowing stale metadata to authorize a new download
  would make offline mode unsafe.

## Consequences

- E12.2 can implement source adapters without deciding installation or scoring.
- E12.3 owns publisher verification, artifact hashing, and immutable pinning; source
  adapters preserve claims and evidence but do not declare them verified.
- Cached results remain useful for offline explanation while installs fail closed
  unless exact verified bytes are present.
- General search is supported as a last-resort route without allowing it to inherit
  trust from the resolver that later pins its content.
- Source-specific schemas and limits are isolated behind adapters, at the cost of
  maintaining normalization and conformance fixtures for each source.

## Follow-up questions and owning issues

No question below blocks this decision; each is assigned to an existing explicit
follow-up issue.

- **#108 (E12.2):** confirm the official MCP Registry's production pagination,
  conditional-request, quota, and schema-version behavior with recorded fixtures;
  define default TTLs from measured behavior rather than guesses.
- **#108 (E12.2):** decide whether GitHub GraphQL is needed after measuring REST
  request cost, and specify authenticated versus anonymous cache partitions.
- **#109 (E12.3):** define the evidence policy for “verified publisher” across
  registry namespaces, GitHub organizations/domains, signatures, and attestations.
- **#109 (E12.3):** standardize normalized-tree hashing for skills/plugins and the
  quarantine/retention rules for immutable artifacts.
- **#111 (E12.5):** define manifest recursion and static-scan boundaries before any
  resolved skill, plugin, MCP server, or CLI package can be approved for install.

## Primary references

- MCP Registry documentation and API: <https://modelcontextprotocol.io/registry/about>
  and <https://registry.modelcontextprotocol.io/docs>
- MCP Registry source and API schema: <https://github.com/modelcontextprotocol/registry>
- npm package metadata and cache/integrity behavior:
  <https://docs.npmjs.com/cli/v11/commands/npm-view>,
  <https://docs.npmjs.com/cli/v11/commands/npm-cache>, and
  <https://docs.npmjs.com/cli/v11/using-npm/config#offline>
- PyPI JSON/Index APIs and integrity metadata:
  <https://docs.pypi.org/api/json/>, <https://docs.pypi.org/api/index-api/>, and
  <https://docs.pypi.org/attestations/>
- Homebrew formula API and download cache:
  <https://formulae.brew.sh/docs/api/> and <https://docs.brew.sh/Manpage>
- GitHub repository, commit, release, search, and rate-limit APIs:
  <https://docs.github.com/en/rest/repos>,
  <https://docs.github.com/en/rest/commits/commits>,
  <https://docs.github.com/en/rest/releases>,
  <https://docs.github.com/en/rest/search>, and
  <https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api>
- Claude Code plugin marketplaces:
  <https://docs.anthropic.com/en/docs/claude-code/plugin-marketplaces>
- Anthropic skills repository: <https://github.com/anthropics/skills>
- OpenAI skills repository: <https://github.com/openai/skills>
- skills.sh catalog: <https://skills.sh/>
- Smithery catalog: <https://smithery.ai/>
