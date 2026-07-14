from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vibe.remote.cache import ResponseCache
from vibe.remote.models import (
    CacheStatus,
    CapabilityKind,
    RemoteCandidate,
    SourceTier,
)
from vibe.remote.registry import RegistryClient, RegistryTransport

FIXTURE_PAYLOAD: dict[str, Any] = {
    "servers": [
        {
            "name": "io.example/catalog-server",
            "version": "1.2.3",
            "description": "Search a product catalog",
            "publisher": "Example, Inc.",
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@example/catalog-server",
                    "version": "1.2.3",
                    "fileSha256": "abc123def456",
                    "permissions": ["network", "read-project"],
                }
            ],
        }
    ]
}


class FakeTransport:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def get(self, path: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        self.calls.append((path, params))
        return self.payload


class FailingTransport:
    def get(self, path: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        raise AssertionError(f"transport touched in offline mode: {path} {params}")


def client(tmp_path: Path, transport: RegistryTransport) -> RegistryClient:
    return RegistryClient(
        transport=transport,
        cache=ResponseCache(tmp_path / "vibe-home", ttl_seconds=300),
    )


def test_search_normalizes_fixture_payloads(tmp_path: Path) -> None:
    transport = FakeTransport(FIXTURE_PAYLOAD)

    result = client(tmp_path, transport).search("catalog-search")

    assert result.cache_status is CacheStatus.FRESH
    assert result.candidates == (
        RemoteCandidate(
            candidate_ref="npm:@example/catalog-server@1.2.3",
            name="io.example/catalog-server",
            kind=CapabilityKind.MCP_SERVER,
            provides=("catalog-search",),
            version="1.2.3",
            digest="sha256:abc123def456",
            publisher="Example, Inc.",
            permissions_as_declared=("network", "read-project"),
            source_tier=SourceTier.OFFICIAL,
        ),
    )


def test_cache_hit_avoids_transport_and_is_byte_identical(tmp_path: Path) -> None:
    transport = FakeTransport(FIXTURE_PAYLOAD)
    registry = client(tmp_path, transport)

    first = registry.search("catalog-search")
    second = registry.search("catalog-search")

    assert len(transport.calls) == 1
    assert second.cache_status is CacheStatus.FRESH
    assert second.candidate_bytes() == first.candidate_bytes()


def test_offline_mode_never_touches_transport_on_cache_hit(tmp_path: Path) -> None:
    online = client(tmp_path, FakeTransport(FIXTURE_PAYLOAD))
    expected = online.search("catalog-search")
    offline = client(tmp_path, FailingTransport())

    result = offline.search("catalog-search", offline=True)

    assert result.candidates == expected.candidates
    assert result.cache_status is CacheStatus.FRESH


def test_offline_mode_with_cold_cache_returns_explicit_empty_result(tmp_path: Path) -> None:
    result = client(tmp_path, FailingTransport()).search("catalog-search", offline=True)

    assert result.candidates == ()
    assert result.cache_status is CacheStatus.NO_CACHED_DATA
    assert result.message == "no cached data"


def test_fetch_returns_normalized_candidate(tmp_path: Path) -> None:
    transport = FakeTransport({"server": FIXTURE_PAYLOAD["servers"][0]})

    candidate = client(tmp_path, transport).fetch("npm:@example/catalog-server@1.2.3")

    assert candidate is not None
    assert candidate.name == "io.example/catalog-server"
    assert candidate.digest == "sha256:abc123def456"
    assert transport.calls == [("/v0.1/servers/npm:@example%2Fcatalog-server@1.2.3", {})]


def test_client_implements_registry_source_contract(tmp_path: Path) -> None:
    from vibe.remote.registry import RegistrySource

    registry = client(tmp_path, FakeTransport(FIXTURE_PAYLOAD))

    assert isinstance(registry, RegistrySource)
