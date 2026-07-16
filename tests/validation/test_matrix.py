from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from tests.scenarios.builders import build_scenario
from vibe.cli import app
from vibe.commands import run as run_command_module
from vibe.commands.explain_task import CodexScenarioClassification
from vibe.compiler.context import CapabilityCandidate
from vibe.models.capability import Permission
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


def load_acceptance_matrix(path: Path) -> list[tuple[str, str, tuple[str, ...]]]:
    rows: list[tuple[str, str, tuple[str, ...]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 3 or cells[0] in {"ID", "---"} or set(cells[0]) == {"-"}:
            continue
        test_ids = tuple(item.strip() for item in cells[2].split("<br>") if item.strip())
        if not test_ids:
            raise ValueError(f"{cells[0]} must have at least one mapped test")
        rows.append((cells[0], cells[1], test_ids))
    return rows


@pytest.mark.validation
def test_matrix_loader_rejects_expectation_without_mapped_test(tmp_path: Path) -> None:
    matrix = tmp_path / "acceptance-matrix.md"
    matrix.write_text(
        "| ID | Expectation | Tests |\n"
        "| --- | --- | --- |\n"
        "| DESIGN-01 | Reproducible resolution | |\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"DESIGN-01.*mapped test"):
        load_acceptance_matrix(matrix)


ROOT = Path(__file__).parents[2]
MATRIX = ROOT / "docs/evaluation/acceptance-matrix.md"
EXPECTED_IDS = {
    *(f"E{epic}-EXIT" for epic in range(11, 17)),
    *(f"DESIGN-{index:02d}" for index in range(1, 13)),
    "CROSS-01",
    "CROSS-02",
    "CROSS-03",
    *(f"NATIVE-{index:02d}" for index in range(1, 6)),
}


def _test_exists(node_id: str) -> bool:
    path_text, separator, test_name = node_id.partition("::")
    if not separator or not test_name:
        return False
    path = ROOT / path_text
    if not path.is_file():
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == test_name
        for node in tree.body
    )


@pytest.mark.validation
def test_acceptance_matrix_covers_all_expectations_with_existing_tests() -> None:
    rows = load_acceptance_matrix(MATRIX)
    ids = {row[0] for row in rows}
    assert ids == EXPECTED_IDS
    missing = [test_id for _, _, tests in rows for test_id in tests if not _test_exists(test_id)]
    assert missing == []
    artifact = {
        "schema_version": "1",
        "matrix": MATRIX.relative_to(ROOT).as_posix(),
        "expectations": [
            {"id": row_id, "expectation": expectation, "tests": list(tests)}
            for row_id, expectation, tests in rows
        ],
    }
    (ROOT / "tests/results/validation-summary.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class _CompletingServer:
    async def start_thread(self, root: Path) -> str:
        return "validation-thread"

    async def resume_thread(self, thread_id: str) -> str:
        return thread_id

    async def execute_phase(self, thread_id: str, prompt: str) -> PhaseExecutionResult:
        capsule = json.loads(prompt)["context_capsule"]
        conditions = run_command_module._ACTIVE_PLAN_PHASES[capsule["current_phase"]]
        return PhaseExecutionResult(
            phase_id=capsule["current_phase"],
            completed=True,
            completion_evidence=("validated",),
            completion_conditions_met=conditions,
        )

    async def close(self) -> None:
        return None


def _classification() -> CodexScenarioClassification:
    return CodexScenarioClassification(
        scenario=ScenarioId.FEATURE,
        scope=ScopeLevel.LOCAL,
        data_sensitivity=DataSensitivity.PUBLIC,
        reversibility=Reversibility.REVERSIBLE,
        operations=frozenset({TaskOperation.WRITE_PROJECT}),
        risk_level=RiskLevel.MEDIUM,
        workflow_mode=WorkflowMode.STANDARD,
    )


@pytest.mark.validation
def test_fresh_init_can_plan_and_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    root = build_scenario("blank", tmp_path / "project").root
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "goal": "Build a validated project",
                "lifecycle_stage": "active-development",
                "risk_level": "medium",
            }
        ),
        encoding="utf-8",
    )
    initialized = runner.invoke(
        app,
        [
            "init",
            "--path",
            str(root),
            "--run-id",
            "validation-init",
            "--checkpoints",
            str(tmp_path / "init.sqlite3"),
            "--answers",
            str(answers),
            "--confirm",
            "--json",
        ],
    )
    assert initialized.exit_code == 0, initialized.output

    planned = runner.invoke(
        app,
        [
            "plan",
            "--path",
            str(root),
            "--task-id",
            "validation-task",
            "--intent",
            "Add a validation feature",
            "--scenario",
            "feature",
            "--scope",
            "README.md",
            "--acceptance",
            "Feature is verified",
            "--json",
        ],
    )
    assert planned.exit_code == 0, planned.output

    monkeypatch.setattr(
        "vibe.commands.explain_task._classify_with_codex", lambda *_: _classification()
    )
    monkeypatch.setattr(
        run_command_module, "_build_app_server", lambda _command: _CompletingServer()
    )
    executed = runner.invoke(
        app,
        [
            "run",
            "Add a validation feature",
            "--path",
            str(root),
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
    assert executed.exit_code == 0, executed.output
    assert json.loads(executed.stdout)["status"] == "completed"


@pytest.mark.validation
def test_remote_installed_capability_is_used_by_phase_gated_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    built = build_scenario("blank-web-remote", tmp_path / "remote")
    bundle = built.root / ".scenario/registry/browser-testing.json"
    installed = runner.invoke(
        app,
        [
            "install",
            "browser-testing",
            "--path",
            str(built.root),
            "--candidate-file",
            str(bundle),
            "--approve",
        ],
    )
    assert installed.exit_code == 0, installed.output
    lock = yaml.safe_load(
        (built.root / ".ai-project/capabilities.lock").read_text(encoding="utf-8")
    )
    provider = next(
        item for item in lock["providers"] if item["provider_id"] == "skill.browser-testing"
    )
    candidate = CapabilityCandidate(
        capability_id=provider["provider_id"],
        provides=("task-execution",),
        phases=("implement",),
        permissions=frozenset({Permission.READ_PROJECT}),
    )
    monkeypatch.setattr(run_command_module, "_ROUTE_CANDIDATES", (candidate,))
    monkeypatch.setattr(
        "vibe.commands.explain_task._classify_with_codex", lambda *_: _classification()
    )
    server = _CompletingServer()
    monkeypatch.setattr(run_command_module, "_build_app_server", lambda _command: server)

    executed = runner.invoke(
        app,
        [
            "run",
            "Use installed browser verification",
            "--path",
            str(built.root),
            "--checkpoint",
            str(tmp_path / "remote-run.json"),
            "--yes",
            "--json",
        ],
    )
    assert executed.exit_code == 0, executed.output
    assert provider["content_digest"].startswith("sha256:")
    assert json.loads(executed.stdout)["status"] == "completed"
