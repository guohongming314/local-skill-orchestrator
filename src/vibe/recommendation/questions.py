"""Select questions whose answers can change capability recommendations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RecommendationQuestionContext:
    requirements: tuple[str, ...]
    local_capabilities: tuple[str, ...]
    repository_facts: Mapping[str, object]
    unknown_decisions: frozenset[str]


@dataclass(frozen=True)
class AdaptiveQuestion:
    question_id: str
    text: str
    impact: str


def adaptive_questions(
    context: RecommendationQuestionContext,
) -> tuple[AdaptiveQuestion, ...]:
    """Return recommendation-changing questions in stable product order."""
    questions: list[AdaptiveQuestion] = []

    if (
        "browser.validation" in context.requirements
        and "cli.playwright" in context.local_capabilities
        and "browser.interactive-debugging" in context.unknown_decisions
    ):
        questions.append(
            AdaptiveQuestion(
                question_id="browser.interactive-debugging",
                text="Do you need interactive browser debugging and control?",
                impact=(
                    "Yes adds interactive browser-control candidates; otherwise the existing "
                    "runner remains preferred."
                ),
            )
        )

    if (
        "project.continuity-memory" in context.requirements
        and context.repository_facts.get("project.lifecycle") != "exploration"
        and "memory.persistence" in context.unknown_decisions
    ):
        questions.append(
            AdaptiveQuestion(
                question_id="memory.persistence",
                text="Should project memory persist across work sessions?",
                impact=(
                    "Yes adds persistent candidates and requires choosing a storage boundary."
                ),
            )
        )

    return tuple(questions)
