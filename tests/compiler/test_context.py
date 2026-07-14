from __future__ import annotations

from vibe.compiler.context import (
    CapabilityCandidate,
    ContextSource,
    SourceKind,
    capsule_is_valid,
    compile_context_capsule,
)
from vibe.compiler.intent import TaskIntent
from vibe.models.risk import RiskLevel
from vibe.models.task import TaskPhase, TaskPlan, WorkflowMode
from vibe.workflows.scenarios import ScenarioId


def plan(*, capability_ids: tuple[str, ...] = ()) -> TaskPlan:
    return TaskPlan(
        task_id="task-47",
        intent="Fix the requested change",
        risk_level=RiskLevel.MEDIUM,
        workflow_mode=WorkflowMode.STANDARD,
        acceptance_criteria=("The requested behavior is verified.",),
        phases=(
            TaskPhase(
                phase_id="inspect",
                objective="Inspect the change.",
                completion_conditions=("Relevant facts are known.",),
                capability_ids=capability_ids,
            ),
            TaskPhase(
                phase_id="implement",
                objective="Implement the change.",
                completion_conditions=("Change is implemented.",),
            ),
        ),
    )


def candidates() -> tuple[CapabilityCandidate, ...]:
    return (
        CapabilityCandidate(
            "skill.codegraph",
            provides=("code-relationship-analysis",),
            phases=("inspect",),
        ),
        CapabilityCandidate(
            "skill.release",
            provides=("release-automation",),
            phases=("implement",),
        ),
    )


def sources() -> tuple[ContextSource, ...]:
    return (
        ContextSource("repository", "repository-digest", SourceKind.REPOSITORY),
        ContextSource("memory:prior-work", "memory-digest", SourceKind.MEMORY),
    )


def test_readme_edit_selects_zero_extra_capabilities() -> None:
    intent = TaskIntent(
        task_id="task-47",
        summary="Correct a README typo",
        scenario=ScenarioId.DOCUMENTATION,
        scope=("README.md",),
        acceptance_criteria=("README text is corrected.",),
    )

    capsule = compile_context_capsule(
        intent,
        plan(),
        phase="inspect",
        candidates=candidates(),
        sources=sources(),
        head="abc123",
        user_scope_digest="scope-v1",
    )

    assert capsule.selected_capability_ids == ()
    assert capsule.rejected_capability_ids == ("skill.codegraph", "skill.release")


def test_cross_module_bug_selects_only_code_relationship_analysis() -> None:
    intent = TaskIntent(
        task_id="task-47",
        summary="Fix a bug spanning inventory and resolution",
        scenario=ScenarioId.BUG,
        scope=("src/vibe/resolver", "src/vibe/inventory"),
        acceptance_criteria=("The cross-module behavior is fixed.",),
        cross_module=True,
    )

    capsule = compile_context_capsule(
        intent,
        plan(),
        phase="inspect",
        candidates=candidates(),
        sources=sources(),
        head="abc123",
        user_scope_digest="scope-v1",
    )

    assert capsule.selected_capability_ids == ("skill.codegraph",)
    assert capsule.rejected_capability_ids == ("skill.release",)


def test_explicit_phase_capabilities_are_kept_and_memory_is_only_a_lead() -> None:
    intent = TaskIntent(
        task_id="task-47",
        summary="Inspect a bug",
        scenario=ScenarioId.BUG,
        scope=("src/vibe/compiler",),
        acceptance_criteria=("The cause is identified.",),
    )

    capsule = compile_context_capsule(
        intent,
        plan(capability_ids=("repo.reader",)),
        phase="inspect",
        candidates=candidates(),
        sources=sources(),
        head="abc123",
        user_scope_digest="scope-v1",
    )

    assert capsule.selected_capability_ids == ("repo.reader",)
    assert "skill.release" in capsule.rejected_capability_ids
    assert any(
        constraint == (
            "Treat memory:prior-work as a lead; verify it against repository sources."
        )
        for constraint in capsule.constraints
    )


def test_head_user_scope_phase_or_task_scope_changes_invalidate_capsule() -> None:
    intent = TaskIntent(
        task_id="task-47",
        summary="Fix a scoped bug",
        scenario=ScenarioId.BUG,
        scope=("src/vibe/compiler",),
        acceptance_criteria=("The bug is fixed.",),
    )
    capsule = compile_context_capsule(
        intent,
        plan(),
        phase="inspect",
        candidates=candidates(),
        sources=sources(),
        head="abc123",
        user_scope_digest="scope-v1",
    )

    assert capsule_is_valid(
        capsule,
        head="abc123",
        user_scope_digest="scope-v1",
        phase="inspect",
        scope=("src/vibe/compiler",),
    )
    assert not capsule_is_valid(
        capsule,
        head="def456",
        user_scope_digest="scope-v1",
        phase="inspect",
        scope=("src/vibe/compiler",),
    )
    assert not capsule_is_valid(
        capsule,
        head="abc123",
        user_scope_digest="scope-v2",
        phase="inspect",
        scope=("src/vibe/compiler",),
    )
    assert not capsule_is_valid(
        capsule,
        head="abc123",
        user_scope_digest="scope-v1",
        phase="implement",
        scope=("src/vibe/compiler",),
    )
    assert not capsule_is_valid(
        capsule,
        head="abc123",
        user_scope_digest="scope-v1",
        phase="inspect",
        scope=("src/vibe/models",),
    )


def test_compilation_is_deterministic_and_uses_a_positive_token_budget() -> None:
    intent = TaskIntent(
        task_id="task-47",
        summary="Fix a cross-module bug",
        scenario=ScenarioId.BUG,
        scope=("src/z.py", "src/a.py", "src/z.py"),
        acceptance_criteria=("Behavior is fixed.",),
        cross_module=True,
    )
    reversed_candidates = tuple(reversed(candidates()))
    reversed_sources = tuple(reversed(sources()))

    first = compile_context_capsule(
        intent,
        plan(),
        phase="inspect",
        candidates=reversed_candidates,
        sources=reversed_sources,
        head="abc123",
        user_scope_digest="scope-v1",
    )
    second = compile_context_capsule(
        intent,
        plan(),
        phase="inspect",
        candidates=reversed_candidates,
        sources=reversed_sources,
        head="abc123",
        user_scope_digest="scope-v1",
    )
    assert first == second
    assert first.scope == ("src/a.py", "src/z.py")
    assert first.token_budget == 4096
    assert tuple(source.source_id for source in first.sources) == (
        "memory:prior-work",
        "repository",
    )
