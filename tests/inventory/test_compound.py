from __future__ import annotations

from vibe.inventory.adapters.compound import CompoundProductAdapter, CompoundProductSpec
from vibe.inventory.service import InventoryService
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)


def component(
    capability_id: str,
    *,
    permissions: frozenset[Permission] = frozenset(),
    digest: str = "component-digest",
) -> CapabilityManifest:
    return CapabilityManifest(
        capability_id=capability_id,
        name=capability_id,
        kind=CapabilityKind.CLI_TOOL,
        scope=CapabilityScope.USER,
        source=f"fixture://{capability_id}",
        provides=(capability_id,),
        permissions=permissions,
        content_digest=digest,
        verified=True,
    )


def test_codegraph_like_product_normalizes_components_capabilities_and_permissions() -> None:
    product = CompoundProductSpec(
        product_id="codegraph",
        name="CodeGraph",
        components=("cli.codegraph", "mcp.codegraph"),
        provides=("code-navigation", "call-graph", "symbol-search"),
        permissions=frozenset({Permission.READ_PROJECT}),
    )
    adapter = CompoundProductAdapter(
        products=(product,),
        components={
            "cli.codegraph": component(
                "cli.codegraph", permissions=frozenset({Permission.EXECUTE_COMMAND})
            ),
            "mcp.codegraph": component(
                "mcp.codegraph", permissions=frozenset({Permission.READ_PROJECT})
            ),
        },
    )

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.capability_id == "product.codegraph"
    assert result.manifest.kind is CapabilityKind.PLUGIN
    assert result.manifest.provides == ("call-graph", "code-navigation", "symbol-search")
    assert result.manifest.permissions == frozenset(
        {Permission.READ_PROJECT, Permission.EXECUTE_COMMAND}
    )
    assert result.verification.verified
    assert result.verification.details == (
        "component:cli.codegraph",
        "component:mcp.codegraph",
    )


def test_memory_like_product_preserves_declared_network_and_user_config_permissions() -> None:
    product = CompoundProductSpec(
        product_id="memory",
        name="Memory Product",
        components=("cli.memory",),
        provides=("cross-session-memory", "semantic-search"),
        permissions=frozenset({Permission.NETWORK, Permission.READ_USER_CONFIG}),
        scope=CapabilityScope.USER,
    )
    adapter = CompoundProductAdapter(
        products=(product,), components={"cli.memory": component("cli.memory")}
    )

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.scope is CapabilityScope.USER
    assert result.manifest.permissions == frozenset(
        {Permission.NETWORK, Permission.READ_USER_CONFIG}
    )
    assert result.manifest.provides == ("cross-session-memory", "semantic-search")


def test_missing_or_unverified_component_marks_product_unverified() -> None:
    unverified = component("cli.present").model_copy(update={"verified": False})
    product = CompoundProductSpec(
        product_id="partial",
        name="Partial",
        components=("cli.missing", "cli.present"),
        provides=("partial-capability",),
    )
    adapter = CompoundProductAdapter(
        products=(product,), components={"cli.present": unverified}
    )

    result = adapter.scan(adapter.discover()[0])

    assert not result.manifest.verified
    assert result.verification.details == (
        "missing_component:cli.missing",
        "unverified_component:cli.present",
    )


def test_compound_digest_is_stable_for_order_and_changes_with_component_content() -> None:
    first_adapter = CompoundProductAdapter(
        products=(
            CompoundProductSpec(
                product_id="product",
                name="Product",
                components=("component.b", "component.a"),
                provides=("b", "a"),
            ),
        ),
        components={
            "component.a": component("component.a", digest="aaaaaaaa"),
            "component.b": component("component.b", digest="bbbbbbbb"),
        },
    )
    adapter = CompoundProductAdapter(
        products=(
            CompoundProductSpec(
                product_id="product",
                name="Product",
                components=("component.a", "component.b"),
                provides=("a", "b"),
            ),
        ),
        components={
            "component.b": component("component.b", digest="bbbbbbbb"),
            "component.a": component("component.a", digest="aaaaaaaa"),
        },
    )
    first_result = first_adapter.scan(first_adapter.discover()[0])
    second_result = adapter.scan(adapter.discover()[0])

    assert first_result.manifest.content_digest == second_result.manifest.content_digest

    changed = CompoundProductAdapter(
        products=adapter.products,
        components={
            "component.a": component("component.a", digest="changed-content"),
            "component.b": component("component.b", digest="bbbbbbbb"),
        },
    )
    changed_result = changed.scan(changed.discover()[0])
    assert changed_result.manifest.content_digest != second_result.manifest.content_digest


def test_multiple_products_merge_deterministically() -> None:
    products = (
        CompoundProductSpec("zeta", "Zeta", (), ("z",)),
        CompoundProductSpec("alpha", "Alpha", (), ("a",)),
    )
    inventory = InventoryService().scan(
        [CompoundProductAdapter(products=products, components={})]
    )

    assert [item.manifest.capability_id for item in inventory.capabilities] == [
        "product.alpha",
        "product.zeta",
    ]


