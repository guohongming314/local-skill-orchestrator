from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe.cli import app
from vibe.models.capsule import ContextCapsule
from vibe.models.task import TaskPlan

runner = CliRunner()


def arguments(root: Path) -> list[str]:
    return [
        "plan",
        "--path",
        str(root),
        "--task-id",
        "task-48",
        "--intent",
        "Fix a bug across compiler modules",
        "--scenario",
        "bug",
        "--scope",
        "src/vibe/compiler/context.py",
        "--scope",
        "src/vibe/compiler/intent.py",
        "--acceptance",
        "Planning output is reviewable",
        "--cross-module",
    ]


def project_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_plan_json_contains_valid_stable_plan_and_capsule(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")

    first = runner.invoke(app, [*arguments(tmp_path), "--json"])
    second = runner.invoke(app, [*arguments(tmp_path), "--json"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    task_plan = TaskPlan.model_validate(payload["task_plan"])
    capsule = ContextCapsule.model_validate(payload["context_capsule"])
    assert task_plan.task_id == "task-48"
    assert capsule.task_id == task_plan.task_id
    assert capsule.current_phase == "inspect"
    assert capsule.token_budget == 4096


def test_plan_human_output_explains_review_decisions(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")

    result = runner.invoke(app, arguments(tmp_path))

    assert result.exit_code == 0
    for label in (
        "Risk:",
        "Workflow:",
        "Selected capabilities:",
        "Requested permissions:",
        "Excluded capabilities:",
        "Token budget:",
        "Invalidation:",
        "Execution: disabled",
    ):
        assert label in result.stdout


def test_plan_does_not_mutate_project(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    before = project_files(tmp_path)

    result = runner.invoke(app, [*arguments(tmp_path), "--json"])

    assert result.exit_code == 0
    assert project_files(tmp_path) == before


def test_plan_writes_only_explicit_capsule_output(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    output = tmp_path.parent / "capsule.json"
    before = project_files(tmp_path)

    result = runner.invoke(
        app,
        [*arguments(tmp_path), "--capsule-output", str(output), "--json"],
    )

    assert result.exit_code == 0
    assert project_files(tmp_path) == before
    capsule = ContextCapsule.model_validate_json(output.read_text(encoding="utf-8"))
    assert capsule.task_id == "task-48"


def test_plan_record_outcome_persists_manual_soft_routed_execution(tmp_path: Path) -> None:
    from alembic import command
    from sqlalchemy.orm import Session, sessionmaker

    from vibe.persistence.database import create_sqlite_engine, migration_config
    from vibe.persistence.repositories import TaskOutcomeRepository

    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    database = tmp_path / "state.sqlite3"

    result = runner.invoke(
        app,
        [
            *arguments(tmp_path),
            "--record-outcome",
            "--capability-used",
            "analysis.code-relationships",
            "--verification-passed",
            "--user-rework",
            "--database",
            str(database),
        ],
    )

    assert result.exit_code == 0, result.stdout
    command.upgrade(migration_config(database), "head")
    factory = sessionmaker(create_sqlite_engine(database), class_=Session, expire_on_commit=False)
    outcome = TaskOutcomeRepository(factory).get("task-48").outcome
    assert outcome.task_type == "bug"
    assert outcome.workflow == "standard"
    assert outcome.capabilities_used == ("analysis.code-relationships",)
    assert outcome.verification_passed is True
    assert outcome.user_rework is True
