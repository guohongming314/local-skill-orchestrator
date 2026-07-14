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


class SearchResult(VersionedModel):
    candidates: tuple[RemoteCandidate, ...] = ()
    cache_status: CacheStatus
    message: str | None = None

    def candidate_bytes(self) -> bytes:
        """Return canonical bytes suitable for reproducibility comparisons."""
        payload = [candidate.model_dump(mode="json") for candidate in self.candidates]
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
