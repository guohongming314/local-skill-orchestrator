from __future__ import annotations

from dataclasses import replace
from typing import ClassVar

from vibe.inventory.adapters.base import (
    AdapterDiscovery,
    AdapterProvenance,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.inventory.service import InventoryService
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)


def manifest(
    capability_id: str,
    *,
    name: str | None = None,
    provides: tuple[str, ...] = ("format", "lint"),
    permissions: frozenset[Permission] = frozenset(
        {Permission.EXECUTE_COMMAND, Permission.READ_PROJECT}
    ),
) -> CapabilityManifest:
    return CapabilityManifest(
        capability_id=capability_id,
        name=name or capability_id,
        kind=CapabilityKind.CLI_TOOL,
        scope=CapabilityScope.PROJECT,
        source=f"fake://{capability_id}",
        provides=provides,
        permissions=permissions,
        content_digest="deadbeef",
        verified=True,
    )


class FakeAdapter:
    discoveries: ClassVar[dict[str, AdapterScanResult]] = {}

    def __init__(self, adapter_id: str, capability_ids: tuple[str, ...]) -> None:
        self.adapter_id = adapter_id
        self.capability_ids = capability_ids

    def discover(self) -> tuple[AdapterDiscovery, ...]:
        return tuple(AdapterDiscovery(locator=item) for item in self.capability_ids)

    def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
        result = self.discoveries[discovery.locator]
        return replace(
            result,
            provenance=replace(result.provenance, adapter_id=self.adapter_id),
        )


def result(item: CapabilityManifest, *, adapter_id: str = "placeholder") -> AdapterScanResult:
    return AdapterScanResult(
        manifest=item,
        provenance=AdapterProvenance(adapter_id=adapter_id, locator=item.source),
        verification=AdapterVerification(verified=True, details=("synthetic",)),
    )


def test_multiple_adapters_merge_deterministically() -> None:
    FakeAdapter.discoveries = {
        "alpha": result(manifest("alpha")),
        "beta": result(manifest("beta")),
    }
    first = InventoryService().scan(
        [FakeAdapter("z-adapter", ("beta",)), FakeAdapter("a-adapter", ("alpha",))]
    )
    second = InventoryService().scan(
        [FakeAdapter("a-adapter", ("alpha",)), FakeAdapter("z-adapter", ("beta",))]
    )

    assert [item.manifest.capability_id for item in first.capabilities] == ["alpha", "beta"]
    assert first == second
    assert first.capabilities[0].provenance.adapter_id == "a-adapter"
    assert first.capabilities[0].verification.details == ("synthetic",)


def test_duplicate_capability_ids_are_excluded_with_explicit_diagnostic() -> None:
    FakeAdapter.discoveries = {"shared": result(manifest("shared"))}

    inventory = InventoryService().scan(
        [FakeAdapter("adapter-b", ("shared",)), FakeAdapter("adapter-a", ("shared",))]
    )

    assert inventory.capabilities == ()
    assert len(inventory.diagnostics) == 1
    diagnostic = inventory.diagnostics[0]
    assert diagnostic.code == "duplicate_capability_id"
    assert diagnostic.capability_id == "shared"
    assert diagnostic.adapter_ids == ("adapter-a", "adapter-b")


def test_identical_project_capability_shadows_user_copy() -> None:
    project = manifest("shared")
    user = project.model_copy(
        update={"scope": CapabilityScope.USER, "source": "fake://user/shared"}
    )
    FakeAdapter.discoveries = {
        "project": result(project),
        "user": result(user),
    }

    inventory = InventoryService().scan(
        [FakeAdapter("agent-skill", ("user", "project"))]
    )

    assert len(inventory.capabilities) == 1
    assert inventory.capabilities[0].manifest.scope is CapabilityScope.PROJECT
    assert inventory.diagnostics == ()


def test_different_project_and_user_capabilities_remain_a_conflict() -> None:
    project = manifest("shared")
    user = project.model_copy(
        update={
            "scope": CapabilityScope.USER,
            "source": "fake://user/shared",
            "content_digest": "changed-digest",
        }
    )
    FakeAdapter.discoveries = {
        "project": result(project),
        "user": result(user),
    }

    inventory = InventoryService().scan(
        [FakeAdapter("agent-skill", ("project", "user"))]
    )

    assert inventory.capabilities == ()
    assert inventory.diagnostics[0].code == "duplicate_capability_id"


def test_broken_adapter_is_isolated_from_successful_scan() -> None:
    class BrokenAdapter:
        adapter_id = "broken"

        def discover(self) -> tuple[AdapterDiscovery, ...]:
            raise RuntimeError("boom")

        def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
            raise AssertionError("scan must not be called")

    FakeAdapter.discoveries = {"healthy": result(manifest("healthy"))}

    inventory = InventoryService().scan([BrokenAdapter(), FakeAdapter("healthy", ("healthy",))])

    assert [item.manifest.capability_id for item in inventory.capabilities] == ["healthy"]
    assert [(item.adapter_id, item.code) for item in inventory.diagnostics] == [
        ("broken", "adapter_discovery_failed")
    ]
    assert "RuntimeError: boom" in inventory.diagnostics[0].message


def test_one_broken_discovery_does_not_hide_other_results_from_adapter() -> None:
    class PartlyBrokenAdapter(FakeAdapter):
        def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
            if discovery.locator == "bad":
                raise ValueError("invalid candidate")
            return super().scan(discovery)

    FakeAdapter.discoveries = {"good": result(manifest("good"))}

    inventory = InventoryService().scan([PartlyBrokenAdapter("partial", ("bad", "good"))])

    assert [item.manifest.capability_id for item in inventory.capabilities] == ["good"]
    assert inventory.diagnostics[0].code == "adapter_scan_failed"
    assert inventory.diagnostics[0].locator == "bad"


def test_digest_normalizes_semantically_unordered_manifest_fields() -> None:
    first_manifest = manifest(
        "tool",
        provides=("lint", "format"),
        permissions=frozenset({Permission.READ_PROJECT, Permission.EXECUTE_COMMAND}),
    )
    second_manifest = manifest(
        "tool",
        provides=("format", "lint"),
        permissions=frozenset({Permission.EXECUTE_COMMAND, Permission.READ_PROJECT}),
    )
    FakeAdapter.discoveries = {"tool": result(first_manifest)}
    first = InventoryService().scan([FakeAdapter("fake", ("tool",))])
    FakeAdapter.discoveries = {"tool": result(second_manifest)}
    second = InventoryService().scan([FakeAdapter("fake", ("tool",))])

    assert first.inventory_digest == second.inventory_digest


def test_digest_changes_when_normalized_manifest_content_changes() -> None:
    FakeAdapter.discoveries = {"tool": result(manifest("tool", name="Before"))}
    before = InventoryService().scan([FakeAdapter("fake", ("tool",))])
    FakeAdapter.discoveries = {"tool": result(manifest("tool", name="After"))}
    after = InventoryService().scan([FakeAdapter("fake", ("tool",))])

    assert before.inventory_digest != after.inventory_digest
