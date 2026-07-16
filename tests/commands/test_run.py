from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibe.cli import app
from vibe.commands import run as run_command_module
from vibe.commands.explain_task import CodexScenarioClassification
from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    RiskLevel,
    ScopeLevel,
    TaskOperation,
)
from vibe.models.task import WorkflowMode
from vibe.workflows.scenarios import ScenarioId
from vibe.workflows.task_runner import PhaseExecutionResult

pytestmark = pytest.mark.validation

runner = CliRunner()


def test_run_help_marks_command_as_deprecated_compatibility_only() -> None:
    result = runner.invoke(app, ["run", "--help"])
    help_text = " ".join(result.stdout.split())

    assert result.exit_code == 0
    assert "deprecated" in help_text.lower()
    assert "compatibility" in help_text.lower()
    assert "current Codex conversation" in help_text
    assert "Codex-native Skills" in help_text


class CompletingAppServer:
    async def start_thread(self, root: Path) -> str:
        return "thread-cli"

    async def resume_thread(self, thread_id: str) -> str:
        return thread_id

    async def execute_phase(self, thread_id: str, prompt: str) -> PhaseExecutionResult:
        payload = json.loads(prompt)
        capsule = payload["context_capsule"]
        conditions = run_command_module._ACTIVE_PLAN_PHASES[capsule["current_phase"]]
        return PhaseExecutionResult(
            phase_id=capsule["current_phase"],
            completed=True,
            completion_evidence=("verified",),
            completion_conditions_met=conditions,
        )

    async def close(self) -> None:
        return None


def test_run_uses_natural_language_classification_and_deterministic_risk_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        "vibe.commands.explain_task._classify_with_codex",
        lambda _task, _root: CodexScenarioClassification(
            scenario=ScenarioId.FEATURE,
            scope=ScopeLevel.LOCAL,
            data_sensitivity=DataSensitivity.PUBLIC,
            reversibility=Reversibility.REVERSIBLE,
            operations=frozenset({TaskOperation.WRITE_PROJECT}),
            risk_level=RiskLevel.LOW,
            workflow_mode=WorkflowMode.FAST,
        ),
    )
    monkeypatch.setattr(
        run_command_module, "_build_app_server", lambda _command: CompletingAppServer()
    )

    result = runner.invoke(
        app,
        [
            "run",
            "Add a small feature",
            "--path",
            str(tmp_path),
            "--scope",
            "README.md",
            "--acceptance",
            "Feature is verified",
            "--checkpoint",
            str(tmp_path / "run.json"),
            "--yes",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert result.stderr.count("deprecated") == 1
    assert "compatibility" in result.stderr
    assert payload["status"] == "completed"
    assert payload["risk_level"] == "medium"
    assert payload["workflow_mode"] == "standard"


def test_completed_run_records_outcome_in_local_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic import command
    from sqlalchemy.orm import Session, sessionmaker

    from vibe.persistence.database import create_sqlite_engine, migration_config
    from vibe.persistence.repositories import TaskOutcomeRepository

    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    database = tmp_path / "state.sqlite3"
    monkeypatch.setattr(
        "vibe.commands.explain_task._classify_with_codex",
        lambda _task, _root: CodexScenarioClassification(
            scenario=ScenarioId.FEATURE,
            scope=ScopeLevel.LOCAL,
            data_sensitivity=DataSensitivity.PUBLIC,
            reversibility=Reversibility.REVERSIBLE,
            operations=frozenset({TaskOperation.WRITE_PROJECT}),
            risk_level=RiskLevel.MEDIUM,
            workflow_mode=WorkflowMode.STANDARD,
        ),
    )
    monkeypatch.setattr(
        run_command_module, "_build_app_server", lambda _command: CompletingAppServer()
    )

    result = runner.invoke(
        app,
        [
            "run",
            "Add a small feature",
            "--path",
            str(tmp_path),
            "--checkpoint",
            str(tmp_path / "run.json"),
            "--database",
            str(database),
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.stdout
    command.upgrade(migration_config(database), "head")
    factory = sessionmaker(create_sqlite_engine(database), class_=Session, expire_on_commit=False)
    task_id = "run-" + __import__("hashlib").sha256(b"Add a small feature").hexdigest()[:12]
    outcome = TaskOutcomeRepository(factory).get(task_id).outcome
    assert outcome.task_type == "feature"
    assert outcome.workflow == "standard"
    assert outcome.verification_passed is True
