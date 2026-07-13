"""Deterministic aggregation of local capability adapters."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from vibe.inventory.adapters.base import AdapterScanResult, CapabilityAdapter


@dataclass(frozen=True)
class InventoryDiagnostic:
    """A stable diagnostic emitted without aborting the complete inventory."""

    adapter_id: str
    code: str
    message: str
    capability_id: str | None = None
    locator: str | None = None
    adapter_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class InventoryResult:
    """Accepted capabilities, diagnostics, and their deterministic digest."""

    capabilities: tuple[AdapterScanResult, ...]
    diagnostics: tuple[InventoryDiagnostic, ...]
    inventory_digest: str


class InventoryService:
    """Scan adapters independently and merge their normalized manifests."""

    def scan(self, adapters: Iterable[CapabilityAdapter]) -> InventoryResult:
        scanned: list[AdapterScanResult] = []
        diagnostics: list[InventoryDiagnostic] = []

        for adapter in sorted(adapters, key=lambda item: item.adapter_id):
            try:
                discoveries = sorted(adapter.discover(), key=lambda item: item.locator)
            except Exception as error:
                diagnostics.append(
                    InventoryDiagnostic(
                        adapter_id=adapter.adapter_id,
                        code="adapter_discovery_failed",
                        message=_error_message(error),
                    )
                )
                continue

            for discovery in discoveries:
                try:
                    scanned.append(adapter.scan(discovery))
                except Exception as error:
                    diagnostics.append(
                        InventoryDiagnostic(
                            adapter_id=adapter.adapter_id,
                            code="adapter_scan_failed",
                            message=_error_message(error),
                            locator=discovery.locator,
                        )
                    )

        by_capability: dict[str, list[AdapterScanResult]] = defaultdict(list)
        for item in scanned:
            by_capability[item.manifest.capability_id].append(item)

        accepted: list[AdapterScanResult] = []
        for capability_id in sorted(by_capability):
            candidates = by_capability[capability_id]
            if len(candidates) == 1:
                accepted.append(candidates[0])
                continue
            adapter_ids = tuple(sorted(item.provenance.adapter_id for item in candidates))
            diagnostics.append(
                InventoryDiagnostic(
                    adapter_id=adapter_ids[0],
                    code="duplicate_capability_id",
                    message=(
                        f"capability {capability_id!r} was reported by multiple adapters: "
                        f"{', '.join(adapter_ids)}"
                    ),
                    capability_id=capability_id,
                    adapter_ids=adapter_ids,
                )
            )

        accepted.sort(
            key=lambda item: (
                item.manifest.capability_id,
                item.provenance.adapter_id,
                item.provenance.locator,
            )
        )
        diagnostics.sort(key=_diagnostic_key)
        capabilities = tuple(accepted)
        return InventoryResult(
            capabilities=capabilities,
            diagnostics=tuple(diagnostics),
            inventory_digest=_inventory_digest(capabilities),
        )


def _error_message(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def _diagnostic_key(item: InventoryDiagnostic) -> tuple[str, str, str, str, tuple[str, ...]]:
    return (
        item.adapter_id,
        item.code,
        item.capability_id or "",
        item.locator or "",
        item.adapter_ids,
    )


def _inventory_digest(capabilities: tuple[AdapterScanResult, ...]) -> str:
    normalized = [_normalized_manifest(item) for item in capabilities]
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _normalized_manifest(item: AdapterScanResult) -> dict[str, Any]:
    manifest = item.manifest.model_dump(mode="json")
    manifest["provides"] = sorted(manifest["provides"])
    manifest["permissions"] = sorted(manifest["permissions"])
    return manifest
