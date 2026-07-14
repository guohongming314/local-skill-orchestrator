"""Read-only client for the official MCP Registry contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, cast, runtime_checkable
from urllib.parse import quote

from vibe.remote.cache import ResponseCache
from vibe.remote.models import (
    CacheStatus,
    CapabilityKind,
    RemoteCandidate,
    SearchResult,
    SourceTier,
)


class RegistryTransport(Protocol):
    def get(self, path: str, params: Mapping[str, str]) -> Mapping[str, Any]: ...


@runtime_checkable
class RegistrySource(Protocol):
    """Read-only normalized remote catalog contract."""

    source_id: str
    source_tier: SourceTier

    def search(self, capability_id: str, *, offline: bool = False) -> SearchResult: ...

    def fetch(self, candidate_ref: str, *, offline: bool = False) -> RemoteCandidate | None: ...


class RegistryClient:
    """Normalize registry metadata without scoring, verifying, or installing it."""

    source_id = "io.modelcontextprotocol.registry"
    source_tier = SourceTier.OFFICIAL

    def __init__(self, *, transport: RegistryTransport, cache: ResponseCache) -> None:
        self._transport = transport
        self._cache = cache

    def search(self, capability_id: str, *, offline: bool = False) -> SearchResult:
        query = capability_id.strip().lower()
        cached = self._cache.get("search-v1", query)
        if cached is not None and (offline or cached.status is CacheStatus.FRESH):
            return self._search_result(cached.payload, cached.status)
        if offline:
            return SearchResult(
                cache_status=CacheStatus.NO_CACHED_DATA,
                message="no cached data",
            )

        payload = self._transport.get("/v0.1/servers", {"search": query})
        normalized = {
            "candidates": [
                self._normalize(server, provides=(query,)).model_dump(mode="json")
                for server in self._records(payload, "servers")
            ]
        }
        self._cache.put("search-v1", query, normalized)
        return self._search_result(normalized, CacheStatus.FRESH)

    def fetch(self, candidate_ref: str, *, offline: bool = False) -> RemoteCandidate | None:
        cached = self._cache.get("fetch-v1", candidate_ref)
        if cached is not None and (offline or cached.status is CacheStatus.FRESH):
            return RemoteCandidate.model_validate(cached.payload["candidate"])
        if offline:
            return None

        path = f"/v0.1/servers/{quote(candidate_ref, safe=':@')}"
        payload = self._transport.get(path, {})
        record = payload.get("server", payload)
        if not isinstance(record, Mapping):
            raise ValueError("registry fetch response does not contain a server record")
        candidate = self._normalize(record)
        self._cache.put("fetch-v1", candidate_ref, {"candidate": candidate.model_dump(mode="json")})
        return candidate

    @staticmethod
    def _records(payload: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
        records = payload.get(key, ())
        if not isinstance(records, list):
            raise ValueError(f"registry response field {key!r} must be a list")
        if not all(isinstance(record, Mapping) for record in records):
            raise ValueError("registry response contains a malformed record")
        return tuple(cast(Mapping[str, Any], record) for record in records)

    def _normalize(
        self, record: Mapping[str, Any], *, provides: tuple[str, ...] = ()
    ) -> RemoteCandidate:
        packages = record.get("packages", ())
        package = packages[0] if isinstance(packages, list) and packages else {}
        if not isinstance(package, Mapping):
            package = {}
        name = str(record.get("name", "")).strip()
        version_value = package.get("version", record.get("version"))
        version = str(version_value) if version_value is not None else None
        identifier = str(package.get("identifier", name))
        registry_type = str(package.get("registryType", "registry"))
        candidate_ref = f"{registry_type}:{identifier}"
        if version:
            candidate_ref += f"@{version}"
        digest_value = package.get("fileSha256") or package.get("integrity")
        digest = str(digest_value) if digest_value is not None else None
        if digest and ":" not in digest:
            digest = f"sha256:{digest}"
        permissions = package.get("permissions", record.get("permissions", ()))
        declared = (
            tuple(sorted(str(item) for item in permissions))
            if isinstance(permissions, list)
            else ()
        )
        publisher_value = record.get("publisher")
        return RemoteCandidate(
            candidate_ref=candidate_ref,
            name=name,
            kind=CapabilityKind.MCP_SERVER,
            provides=provides,
            version=version,
            digest=digest,
            publisher=str(publisher_value) if publisher_value is not None else None,
            permissions_as_declared=declared,
            source_tier=self.source_tier,
        )

    @staticmethod
    def _search_result(payload: Mapping[str, Any], status: CacheStatus) -> SearchResult:
        candidates = payload.get("candidates", ())
        if not isinstance(candidates, list):
            raise ValueError("cached registry candidates must be a list")
        return SearchResult(
            candidates=tuple(RemoteCandidate.model_validate(item) for item in candidates),
            cache_status=status,
        )
