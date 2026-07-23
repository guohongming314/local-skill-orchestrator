from vibe.recommendation.search_terms import DiscoveryQueryContext, discovery_queries


def test_queries_combine_capability_repository_and_user_product_leads() -> None:
    context = DiscoveryQueryContext(
        capability="code.optimization",
        languages=("python", "typescript"),
        frameworks=("fastapi", "react"),
        user_product_leads=("Ponytail",),
    )

    queries = discovery_queries(context)

    assert queries[0] == "code.optimization"
    assert "python typescript code optimization refactoring static analysis" in queries
    assert "Ponytail code optimization" in queries


def test_unknown_product_lead_is_preserved_without_verified_identity() -> None:
    queries = discovery_queries(
        DiscoveryQueryContext(
            capability="development.design",
            user_product_leads=("supperpowers",),
        )
    )

    assert "supperpowers development design" in queries
