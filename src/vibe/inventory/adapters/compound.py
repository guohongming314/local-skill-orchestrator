"""Declarative normalization for compound local capability products."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from vibe.inventory.adapters.base import (
    AdapterDiscovery,
    AdapterProvenance,
    AdapterScanError,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)


@dataclass(frozen=True)
class CompoundProductSpec:
    """A product composed from independently discovered capability components."""

    product_id: str
    name: str
    components: tuple[str, ...]
    provides: tuple[str, ...]
    permissions: frozenset[Permission] = frozenset()
    scope: CapabilityScope = CapabilityScope.USER
    kind: CapabilityKind = CapabilityKind.PLUGIN


class CompoundProductAdapter:
    """Aggregate declared components into one explainable product manifest."""

    adapter_id = "compound-product"

    def __init__(
        self,
        *,
        products: tuple[CompoundProductSpec, ...],
        components: dict[str, CapabilityManifest],
    ) -> None:
        by_id = {product.product_id: product for product in products}
        if len(by_id) != len(products):
            raise ValueError("compound product IDs must be unique")
        self._products = by_id
        self._components = dict(components)

    @property
    def products(self) -> tuple[CompoundProductSpec, ...]:
        return tuple(self._products[item] for item in sorted(self._products))

    def discover(self) -> tuple[AdapterDiscovery, ...]:
        return tuple(AdapterDiscovery(locator=item) for item in sorted(self._products))

    def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
        try:
            product = self._products[discovery.locator]
        except KeyError as error:
            raise AdapterScanError(f"unknown compound product: {discovery.locator}") from error

        permissions = set(product.permissions)
        details: list[str] = []
        component_digests: dict[str, str | None] = {}
        for component_id in sorted(set(product.components)):
            component = self._components.get(component_id)
            if component is None:
                details.append(f"missing_component:{component_id}")
                component_digests[component_id] = None
                continue
            permissions.update(component.permissions)
            component_digests[component_id] = component.content_digest
            if component.verified:
                details.append(f"component:{component_id}")
            else:
                details.append(f"unverified_component:{component_id}")

        verified = all(detail.startswith("component:") for detail in details)
        digest_payload = {
            "components": component_digests,
            "kind": product.kind.value,
            "name": product.name,
            "permissions": sorted(permission.value for permission in permissions),
            "product_id": product.product_id,
            "provides": sorted(set(product.provides)),
            "scope": product.scope.value,
        }
        digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        manifest = CapabilityManifest(
            capability_id=f"product.{product.product_id}",
            name=product.name,
            kind=product.kind,
            scope=product.scope,
            source=f"compound://{product.product_id}",
            provides=tuple(sorted(set(product.provides))),
            permissions=frozenset(permissions),
            content_digest=digest,
            verified=verified,
        )
        return AdapterScanResult(
            manifest=manifest,
            provenance=AdapterProvenance(
                adapter_id=self.adapter_id,
                locator=discovery.locator,
            ),
            verification=AdapterVerification(
                verified=verified,
                details=tuple(sorted(details)),
            ),
        )
