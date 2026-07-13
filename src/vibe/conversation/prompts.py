"""User-facing project interview prompts without implementation tool names."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplate:
    category: str
    text: str


QUESTION_ORDER = (
    "project.goal",
    "project.lifecycle",
    "risk.tolerance",
    "constraints.deadline",
    "constraints.compliance",
    "permissions.write_project",
    "permissions.execute_command",
    "permissions.network",
    "preferences.workflow",
    "preferences.testing",
)

PROMPTS: dict[str, PromptTemplate] = {
    "project.lifecycle": PromptTemplate(
        "lifecycle", "What lifecycle stage should this project target?"
    ),
    "risk.tolerance": PromptTemplate(
        "risk", "What level of implementation risk is acceptable?"
    ),
    "constraints.deadline": PromptTemplate(
        "constraints", "Is there a delivery deadline or time constraint?"
    ),
    "constraints.compliance": PromptTemplate(
        "constraints", "Are there compliance or data-handling constraints?"
    ),
    "permissions.write_project": PromptTemplate(
        "permissions", "May the project files be changed when you approve the plan?"
    ),
    "permissions.execute_command": PromptTemplate(
        "permissions", "May local verification commands be executed?"
    ),
    "permissions.network": PromptTemplate(
        "permissions", "May network access be used when local evidence is insufficient?"
    ),
    "preferences.workflow": PromptTemplate(
        "preferences", "Do you have a preferred development workflow?"
    ),
    "preferences.testing": PromptTemplate(
        "preferences", "Do you have a preferred testing strategy?"
    ),
}


def goal_prompt(*, empty_project: bool) -> PromptTemplate:
    if empty_project:
        text = "What would you like to create in this new project?"
    else:
        text = "What would you like to change in this existing project?"
    return PromptTemplate("goal", text)
