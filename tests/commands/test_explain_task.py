from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibe.cli import app
from vibe.commands import explain_task
from vibe.commands.explain_task import (
    CodexScenarioClassification,
    TaskExplanation,
)
from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    RiskLevel,
    ScopeLevel,
    TaskOperation,
)
from vibe.models.task import WorkflowMode
from vibe.workflows.scenarios import ScenarioId

runner = CliRunner()


def _classification(
    scenario: ScenarioId,
    *,
    operations: frozenset[TaskOperation],
) -> CodexScenarioClassification:
    return CodexScenarioClassification(
        scenario=scenario,
        scope=ScopeLevel.LOCAL,
        data_sensitivity=DataSensitivity.PUBLIC,
        reversibility=Reversibility.REVERSIBLE,
        operations=operations,
        risk_level=(
            RiskLevel.CRITICAL
            if TaskOperation.HANDLE_PAYMENT in operations
            else RiskLevel.LOW
        ),
        workflow_mode=(
            WorkflowMode.RIGOROUS
            if TaskOperation.HANDLE_PAYMENT in operations
            else WorkflowMode.FAST
        ),
    )


def test_high_risk_payment_task_explains_rigorous_with_security_review_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        explain_task,
        "_classify_with_codex",
        lambda _task, _root: _classification(
            ScenarioId.FEATURE,
            operations=frozenset(
                {TaskOperation.WRITE_PROJECT, TaskOperation.HANDLE_PAYMENT}
            ),
        ),
    )

    result = runner.invoke(
        app,
        ["explain-task", "Add payment capture retries", "--path", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Workflow: rigorous" in result.stdout
    assert "Risk: critical" in result.stdout
    assert "Phase: security-review" in result.stdout
    assert "Execution: disabled" in result.stdout


def test_typo_fix_task_explains_fast_with_zero_extra_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "README.md").write_text("teh\n", encoding="utf-8")
    monkeypatch.setattr(
        explain_task,
        "_classify_with_codex",
        lambda _task, _root: _classification(
            ScenarioId.DOCUMENTATION,
            operations=frozenset(),
        ),
    )

    first = runner.invoke(
        app,
        ["explain-task", "Fix a README typo", "--path", str(tmp_path), "--json"],
    )
    second = runner.invoke(
        app,
        ["explain-task", "Fix a README typo", "--path", str(tmp_path), "--json"],
    )

    assert first.exit_code == 0
    assert first.stdout == second.stdout
    explanation = TaskExplanation.model_validate(json.loads(first.stdout))
    assert explanation.workflow_mode.value == "fast"
    assert all(not phase.selected for phase in explanation.phases)
    assert all(not phase.deferred for phase in explanation.phases)


def test_disagreement_with_deterministic_signals_asks_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        explain_task,
        "_classify_with_codex",
        lambda _task, _root: CodexScenarioClassification(
            scenario=ScenarioId.BUG,
            scope=ScopeLevel.LOCAL,
            data_sensitivity=DataSensitivity.PUBLIC,
            reversibility=Reversibility.REVERSIBLE,
            operations=frozenset({TaskOperation.WRITE_PROJECT}),
            risk_level=RiskLevel.LOW,
            workflow_mode=WorkflowMode.FAST,
        ),
    )

    result = runner.invoke(
        app,
        ["explain-task", "Fix checkout bug", "--path", str(tmp_path)],
        input="y\n",
    )

    assert result.exit_code == 0
    assert "Codex classification disagrees with deterministic risk signals" in result.stdout
    assert "Workflow: standard" in result.stdout


def test_scenario_override_bypasses_codex_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")

    def unexpected(*_args: object) -> CodexScenarioClassification:
        raise AssertionError("Codex classification should be bypassed")

    monkeypatch.setattr(explain_task, "_classify_with_codex", unexpected)
    result = runner.invoke(
        app,
        [
            "explain-task",
            "Review this change",
            "--path",
            str(tmp_path),
            "--scenario",
            "review",
            "--json",
        ],
    )

    assert result.exit_code == 0
    explanation = TaskExplanation.model_validate_json(result.stdout)
    assert explanation.scenario is ScenarioId.REVIEW
