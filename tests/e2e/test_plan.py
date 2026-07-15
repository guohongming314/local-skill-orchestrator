from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from vibe.cli import app
from vibe.evaluation.samples import TaskSampleSet
from vibe.models.capsule import ContextCapsule
from vibe.models.task import TaskPlan

pytestmark = pytest.mark.validation

runner = CliRunner()


def _invoke(
    root: Path,
    *,
    task_id: str,
    intent: str,
    scenario: str,
    scope: tuple[str, ...],
    cross_module: bool = False,
) -> tuple[TaskPlan, ContextCapsule]:
    args = [
        "plan",
        "--path",
        str(root),
        "--task-id",
        task_id,
        "--intent",
        intent,
        "--scenario",
        scenario,
        "--acceptance",
        "The requested result is verified",
        "--json",
    ]
    for item in scope:
        args.extend(("--scope", item))
    if cross_module:
        args.append("--cross-module")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    return (
        TaskPlan.model_validate(payload["task_plan"]),
        ContextCapsule.model_validate(payload["context_capsule"]),
    )


def _digest(capsule: ContextCapsule) -> str:
    return hashlib.sha256(capsule.model_dump_json().encode()).hexdigest()


def test_low_risk_task_stays_minimal_with_zero_extra_capabilities(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("project\n", encoding="utf-8")

    plan, capsule = _invoke(
        tmp_path,
        task_id="simple-doc",
        intent="Fix a README typo",
        scenario="review",
        scope=("README.md",),
    )

    assert plan.risk_level.value == "low"
    assert plan.workflow_mode.value == "fast"
    assert tuple(phase.phase_id for phase in plan.phases) == ("inspect", "verify")
    assert capsule.selected_capability_ids == ()
    assert capsule.requested_permissions == ()
    assert "automation.release" in capsule.rejected_capability_ids


def test_cross_module_bug_selects_only_read_only_relationship_analysis(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "src/b.py").write_text("B = 2\n", encoding="utf-8")

    plan, capsule = _invoke(
        tmp_path,
        task_id="cross-module",
        intent="Fix a bug across compiler modules",
        scenario="bug",
        scope=("src/a.py", "src/b.py"),
        cross_module=True,
    )

    assert plan.workflow_mode.value == "standard"
    assert capsule.selected_capability_ids == ("analysis.code-relationships",)
    assert capsule.requested_permissions == ("read-project",)
    assert capsule.rejected_capability_ids == ("automation.release",)


def test_security_migration_and_review_receive_correct_rigorous_gates(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("pass\n", encoding="utf-8")

    security, _ = _invoke(
        tmp_path,
        task_id="security",
        intent="Harden authentication token validation",
        scenario="security",
        scope=("app.py",),
    )
    security_phases = {item.phase_id: item for item in security.phases}
    assert security.risk_level.value == "high"
    assert security.workflow_mode.value == "rigorous"
    assert security_phases["approval"].requires_approval
    assert "rollback" in security_phases

    migration, _ = _invoke(
        tmp_path,
        task_id="migration",
        intent="Migrate stored account records",
        scenario="migration",
        scope=("app.py",),
    )
    assert migration.workflow_mode.value == "rigorous"
    assert "rollback" in {item.phase_id for item in migration.phases}
    assert any(item.requires_approval for item in migration.phases)

    review, _ = _invoke(
        tmp_path,
        task_id="review",
        intent="Review the current authentication change",
        scenario="review",
        scope=("app.py",),
    )
    review_phases = {item.phase_id for item in review.phases}
    assert "implement" not in review_phases
    assert "rollback" not in review_phases


def test_memory_source_is_a_non_authoritative_lead(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("project\n", encoding="utf-8")
    (tmp_path / ".memory-provider.json").write_text(
        '{"provider":"local-leads","mode":"lead-only"}\n', encoding="utf-8"
    )

    _, capsule = _invoke(
        tmp_path,
        task_id="memory",
        intent="Investigate a prior intermittent failure",
        scenario="bug",
        scope=("README.md",),
    )

    assert [source.source_id for source in capsule.sources] == [
        "memory:local-leads",
        "repository",
    ]
    assert capsule.constraints == (
        "Treat memory:local-leads as a lead; verify it against repository sources.",
    )


def test_goal_or_scope_change_produces_a_new_capsule_digest(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("project\n", encoding="utf-8")

    _, original = _invoke(
        tmp_path,
        task_id="scope-change",
        intent="Review documentation",
        scenario="review",
        scope=("README.md",),
    )
    _, goal_changed = _invoke(
        tmp_path,
        task_id="scope-change",
        intent="Review documentation for security claims",
        scenario="review",
        scope=("README.md",),
    )
    _, scope_changed = _invoke(
        tmp_path,
        task_id="scope-change",
        intent="Review documentation",
        scenario="review",
        scope=("README.md", "docs/security.md"),
    )

    assert len({_digest(original), _digest(goal_changed), _digest(scope_changed)}) == 3
    assert original.invalidation_conditions != scope_changed.invalidation_conditions


def test_versioned_task_sample_set_has_required_evaluation_coverage() -> None:
    path = Path(__file__).parents[1] / "scenarios/tasks/samples.json"
    payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    sample_set = TaskSampleSet.model_validate(payload)
    assert sample_set.schema_version == "1"
    assert payload["schema_version"] == "1"
    samples = cast(list[dict[str, Any]], payload["samples"])
    assert len({item["sample_id"] for item in samples}) == len(samples)
    counts = {
        difficulty: sum(item["difficulty"] == difficulty for item in samples)
        for difficulty in ("simple", "normal", "high-risk")
    }
    assert counts == {"simple": 30, "normal": 30, "high-risk": 30}
    assert sum("zero-extra-capability" in item["tags"] for item in samples) >= 20
    assert sum(item.get("goal_change") is not None for item in samples) >= 20
    assert sum("capability-conflict" in item["tags"] for item in samples) >= 20
    assert all(item["acceptance"] and item["scope"] for item in samples)
