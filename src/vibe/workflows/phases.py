"""Reusable task phase templates and completion gates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseTemplate:
    phase_id: str
    objective: str
    completion_conditions: tuple[str, ...]


PHASE_TEMPLATES: dict[str, PhaseTemplate] = {
    "inspect": PhaseTemplate(
        "inspect",
        "Inspect relevant project facts and constraints.",
        ("Relevant sources and constraints are identified.",),
    ),
    "design": PhaseTemplate(
        "design",
        "Choose the smallest safe implementation design.",
        ("Design addresses acceptance criteria and identified risks.",),
    ),
    "approval": PhaseTemplate(
        "approval",
        "Obtain explicit approval for high-risk operations.",
        ("An authorized approver explicitly accepts the proposed operation.",),
    ),
    "rollback": PhaseTemplate(
        "rollback",
        "Prepare and verify a rollback strategy before mutation.",
        ("Rollback steps and success checks are documented and feasible.",),
    ),
    "implement": PhaseTemplate(
        "implement",
        "Implement the approved change with the minimum required capabilities.",
        ("Implementation satisfies the planned design without scope expansion.",),
    ),
    "verify": PhaseTemplate(
        "verify",
        "Run focused and project-wide verification gates.",
        ("Acceptance criteria and required quality gates pass.",),
    ),
    "review": PhaseTemplate(
        "review",
        "Review results, risks, and evidence before completion.",
        ("Review has no unresolved blocking finding.",),
    ),
}
