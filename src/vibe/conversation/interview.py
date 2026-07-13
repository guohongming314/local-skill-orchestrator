"""Build a minimal deterministic interview from unresolved project facts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibe.conversation.prompts import PROMPTS, QUESTION_ORDER, PromptTemplate, goal_prompt
from vibe.models.repository import FactConfidence, RepositorySnapshot


@dataclass(frozen=True)
class InterviewInput:
    repository: RepositorySnapshot
    unknowns: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    inventory_summary: tuple[str, ...] = ()
    preferences: Mapping[str, str] | None = None


@dataclass(frozen=True)
class InterviewQuestion:
    question_id: str
    category: str
    text: str
    requires_explicit_confirmation: bool = False


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
    conflicts.update(
        fact.key
        for fact in inputs.repository.facts
        if fact.confidence is FactConfidence.CONFLICT
    )
    unresolved = (set(inputs.unknowns) | conflicts) - confirmed

    questions: list[InterviewQuestion] = []
    for question_id in QUESTION_ORDER:
        if question_id not in unresolved:
            continue
        template = _template(question_id, inputs.repository.is_empty)
        explicit = question_id in conflicts and _is_high_risk(question_id)
        text = template.text
        if explicit:
            text = f"Conflicting high-risk information was found. Please confirm: {text}"
        questions.append(
            InterviewQuestion(
                question_id=question_id,
                category=template.category,
                text=text,
                requires_explicit_confirmation=explicit,
            )
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
