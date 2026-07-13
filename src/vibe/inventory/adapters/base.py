"""Capability adapter contracts shared by all inventory sources."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from vibe.models.capability import CapabilityManifest


@dataclass(frozen=True, order=True)
class AdapterDiscovery:
    """A stable, source-specific locator discovered by an adapter."""

    locator: str


@dataclass(frozen=True)
class AdapterProvenance:
    """Where and how an adapter obtained a capability manifest."""

    adapter_id: str
    locator: str


@dataclass(frozen=True)
class AdapterVerification:
    """Adapter-local verification evidence for a scanned capability."""

    verified: bool
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterScanResult:
    """Normalized output produced by scanning one discovered locator."""

    manifest: CapabilityManifest
    provenance: AdapterProvenance
    verification: AdapterVerification


class AdapterError(RuntimeError):
    """Base class for expected capability adapter failures."""


class AdapterDiscoveryError(AdapterError):
    """Raised when an adapter cannot enumerate its capability sources."""


class AdapterScanError(AdapterError):
    """Raised when an adapter cannot scan one discovered source."""


@runtime_checkable
class CapabilityAdapter(Protocol):
    """Deterministic two-phase interface implemented by capability sources."""

    adapter_id: str

    def discover(self) -> Sequence[AdapterDiscovery]: ...

    def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult: ...
