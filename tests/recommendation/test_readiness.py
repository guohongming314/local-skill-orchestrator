from vibe.recommendation.readiness import evaluate_review_readiness


def test_not_requested_discovery_blocks_install_review_for_important_gap() -> None:
    readiness = evaluate_review_readiness(
        required_gaps=("quality.gates",),
        recommended_gaps=("browser.validation",),
        discovery_status={
            "quality.gates": "not-requested",
            "browser.validation": "not-requested",
        },
        candidate_decisions={},
        unknown_permissions=("network_policy",),
    )

    assert readiness.ready is False
    assert readiness.next_action == "request-discovery-decision"
    assert "quality.gates" in readiness.blocking_requirements


def test_explicit_deferral_allows_configuration_review() -> None:
    readiness = evaluate_review_readiness(
        required_gaps=(),
        recommended_gaps=("browser.validation",),
        discovery_status={"browser.validation": "not-requested"},
        candidate_decisions={"browser.validation": "defer"},
        unknown_permissions=(),
    )

    assert readiness.ready is True
