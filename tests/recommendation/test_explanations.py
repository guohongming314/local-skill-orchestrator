from vibe.recommendation.explanations import RecommendationEvidence, explain_candidate


def test_candidate_explanation_covers_need_fit_permissions_and_alternative() -> None:
    explanation = explain_candidate(
        RecommendationEvidence(
            requirement="browser.validation",
            provider="playwright",
            need_reason="The repository contains a browser-facing application.",
            fit_reasons=("Playwright configuration already exists",),
            permissions=("read-project", "execute-command"),
            verification="verified-local",
            alternative="chrome-devtools",
            alternative_reason=(
                "better for interactive debugging but requires networked MCP runtime"
            ),
        )
    )

    assert "browser-facing" in explanation
    assert "read-project" in explanation
    assert "verified-local" in explanation
    assert "chrome-devtools" in explanation
