"""Normalized models for untrusted remote capability metadata."""

from __future__ import annotations

import json
from enum import IntEnum, StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel


class CapabilityKind(StrEnum):
    MCP_SERVER = "mcp-server"
    AGENT_SKILL = "agent-skill"
    PLUGIN = "plugin"
    CLI_TOOL = "cli-tool"


class SourceTier(IntEnum):
    OFFICIAL = 7
    VERIFIED_PUBLISHER = 8
    COMMUNITY = 9
    GENERAL_SEARCH = 10


class PermissionLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class PublisherVerification(StrEnum):
    UNVERIFIED = "unverified"
    ALLOWLIST = "allowlist"
    ORG_SIGNATURE = "org-signature"


class Provenance(VersionedModel):
    """Verified evidence reusable by the capability lockfile."""

    source: str = Field(min_length=1)
    publisher: str | None = None
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_verified: bool
    publisher_verified: bool
    publisher_verification: PublisherVerification
    digest_verified: bool
    permission_level: PermissionLevel
    reason: str = Field(min_length=1)


class CacheStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    NO_CACHED_DATA = "no-cached-data"


class RemoteCandidate(VersionedModel):
    """Source-declared candidate data; none of these claims are verified."""

    candidate_ref: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: CapabilityKind
    provides: tuple[str, ...] = ()
    version: str | None = None
    digest: str | None = None
    publisher: str | None = None
    permissions_as_declared: tuple[str, ...] = ()
    source_tier: SourceTier
    provenance: Provenance | None = None
    canonical_repository: str | None = None
    revision: str | None = None
    cross_source_ref: str | None = None
    description: str | None = None
    stars: int = Field(default=0, ge=0)
    forks: int = Field(default=0, ge=0)
    adoption: int = Field(default=0, ge=0)
    weekly_adoption: int = Field(default=0, ge=0)
    last_activity: str | None = None
    archived: bool = False
    official: bool = False


class SearchResult(VersionedModel):
    candidates: tuple[RemoteCandidate, ...] = ()
    cache_status: CacheStatus
    message: str | None = None

    def candidate_bytes(self) -> bytes:
        """Return canonical bytes suitable for reproducibility comparisons."""
        payload = [candidate.model_dump(mode="json") for candidate in self.candidates]
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
