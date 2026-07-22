"""Build a minimal deterministic interview from unresolved project facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibe.conversation.prompts import PROMPTS, QUESTION_ORDER, PromptTemplate, goal_prompt
from vibe.models.repository import FactConfidence, RepositorySnapshot
from vibe.recommendation.questions import AdaptiveQuestion


@dataclass(frozen=True)
class InterviewInput:
    repository: RepositorySnapshot
    unknowns: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    inventory_summary: tuple[str, ...] = ()
    preferences: Mapping[str, str] | None = None
    adaptive_questions: tuple[AdaptiveQuestion, ...] = ()


@dataclass(frozen=True)
class InterviewQuestion:
    question_id: str
    category: str
    text: str
    requires_explicit_confirmation: bool = False
    recommended_default: str | None = None
    recommendation_reason: str | None = None
    impact: str | None = None


@dataclass(frozen=True)
class InterviewResult:
    questions: tuple[InterviewQuestion, ...]
    confirmed_fact_keys: tuple[str, ...]
    unresolved_keys: tuple[str, ...]


def build_interview(inputs: InterviewInput) -> InterviewResult:
    """Ask only unresolved high-impact questions in stable product order."""
    confirmed = {
        fact.key
        for fact in inputs.repository.facts
        if fact.confidence is FactConfidence.CONFIRMED
    }
    confirmed.update((inputs.preferences or {}).keys())
    conflicts = set(inputs.conflicts)
    if "project_type" in conflicts:
        conflicts.add("project.type")
    conflicts.update(
        "project.type" if fact.key == "project_type" else fact.key
        for fact in inputs.repository.facts
        if fact.confidence is FactConfidence.CONFLICT
    )
    unresolved = (set(inputs.unknowns) | conflicts) - confirmed
    if inputs.repository.is_empty:
        unresolved.add("project.type")

    questions: list[InterviewQuestion] = []
    for question_id in QUESTION_ORDER:
        if question_id not in unresolved:
            continue
        template = _template(question_id, inputs.repository.is_empty)
        explicit = question_id in conflicts and _is_high_risk(question_id)
        text = template.text
        if explicit:
            text = f"Conflicting high-risk information was found. Please confirm: {text}"
        recommended_default, recommendation_reason = _recommended_default(
            inputs.repository, question_id
        )
        questions.append(
            InterviewQuestion(
                question_id=question_id,
                category=template.category,
                text=text,
                requires_explicit_confirmation=explicit,
                recommended_default=recommended_default,
                recommendation_reason=recommendation_reason,
            )
        )

    questions.extend(
        InterviewQuestion(
            question_id=question.question_id,
            category="recommendation",
            text=question.text,
            impact=question.impact,
        )
        for question in inputs.adaptive_questions
    )

    return InterviewResult(
        questions=tuple(questions),
        confirmed_fact_keys=tuple(sorted(confirmed)),
        unresolved_keys=tuple(question.question_id for question in questions),
    )


def _template(question_id: str, empty_project: bool) -> PromptTemplate:
    if question_id == "project.goal":
        return goal_prompt(empty_project=empty_project)
    return PROMPTS[question_id]


def _is_high_risk(question_id: str) -> bool:
    return question_id.startswith(("risk.", "permissions.", "constraints.compliance"))


def _recommended_default(
    repository: RepositorySnapshot, question_id: str
) -> tuple[str | None, str | None]:
    aliases = {question_id}
    if question_id == "project.type":
        aliases.add("project_type")
    for fact in repository.facts:
        if (
            fact.key in aliases
            and fact.confidence is FactConfidence.INFERRED
            and isinstance(fact.value, str)
        ):
            evidence = ", ".join(fact.sources) or "repository inspection"
            return fact.value, f"Repository evidence from {evidence} supports this default."
    return None, None
