from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.scenarios.builders import build_scenario
from vibe.cli import app
from vibe.codex.exec_fallback import CodexExecFallback
from vibe.conversation.runner import ConversationRunner
from vibe.workflows.checkpoints import SqliteCheckpointStore
from vibe.workflows.state import InitStage, InitStatus

pytestmark = pytest.mark.validation

runner = CliRunner()
FAKE_SERVER = Path(__file__).parents[1] / "fakes" / "fake_interview_app_server.py"
FAKE_EXEC = Path(__file__).parents[1] / "fakes" / "fake_codex_exec.py"


def _patch_conversation(
    monkeypatch: Any,
    tmp_path: Path,
    *,
    server_mode: str = "valid",
    fallback_mode: str = "fail-if-called",
) -> Path:
    from vibe.commands import init as init_module

    state = tmp_path / f"server-{server_mode}.json"
    fallback_invocation = tmp_path / f"fallback-{fallback_mode}.json"
    monkeypatch.setattr(
        init_module,
        "APP_SERVER_COMMAND",
        (sys.executable, str(FAKE_SERVER), server_mode, str(state)),
    )

    class AcceptanceConversationRunner(ConversationRunner):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(
                **kwargs,
                exec_fallback=CodexExecFallback(
                    (
                        sys.executable,
                        str(FAKE_EXEC),
                        fallback_mode,
                        str(fallback_invocation),
                    )
                ),
            )

    monkeypatch.setattr(init_module, "ConversationRunner", AcceptanceConversationRunner)
    return fallback_invocation


def _invoke_conversation(
    root: Path,
    checkpoint: Path,
    *,
    run_id: str,
    answers: str,
    extra: tuple[str, ...] = (),
) -> Any:
    return runner.invoke(
        app,
        [
            "init",
            "--path",
            str(root),
            "--run-id",
            run_id,
            "--checkpoints",
            str(checkpoint),
            "--confirm",
            "--json",
            *extra,
        ],
        input=answers,
    )


def test_blank_repo_conversation_reaches_dry_run(monkeypatch: Any, tmp_path: Path) -> None:
    root = build_scenario("blank", tmp_path / "blank").root
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    _patch_conversation(monkeypatch, tmp_path)
    answers = "\n".join(
        (
            "Build a dependable CLI",
            "CLI tool",
            "active-development",
            "medium",
            "No deadline",
            "No compliance constraints",
            "yes",
            "yes",
            "no",
            "small pull requests",
            "test-first",
        )
    ) + "\n"

    result = _invoke_conversation(
        root,
        tmp_path / "blank.sqlite3",
        run_id="blank-conversation",
        answers=answers,
        extra=("--dry-run",),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload["status"] == "dry-run"
    assert payload["field_sources"]["goal"] == "confirmed"
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_existing_repo_conversation_supports_revision_lock_default_and_apply(
    monkeypatch: Any, tmp_path: Path
) -> None:
    root = build_scenario("python-small", tmp_path / "existing").root
    _patch_conversation(monkeypatch, tmp_path)
    answers = "\n".join(
        (
            "Ship the first goal",
            "lock project.goal",
            "accept default",
            "active-development",
            "low",
            "revise risk.tolerance",
            "high",
            "No deadline",
            "SOC 2",
            "yes",
            "yes",
            "no",
            "small pull requests",
            "test-first",
        )
    ) + "\n"

    result = _invoke_conversation(
        root,
        tmp_path / "existing.sqlite3",
        run_id="existing-conversation",
        answers=answers,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload["status"] == "completed"
    assert payload["locked_decisions"] == ["goal"]
    recorded = json.loads((tmp_path / "server-valid.json").read_text(encoding="utf-8"))
    answer_prompts = [
        json.loads(prompt)
        for prompt in recorded["prompts"]
        if prompt.startswith("{") and "question_id" in json.loads(prompt)
    ]
    project_type = next(
        prompt for prompt in answer_prompts if prompt["question_id"] == "project.type"
    )
    assert project_type["provenance"] == "recommended-default"
    assert payload["blueprint"]["risk_level"] == "high"
    assert (root / ".ai-project/blueprint.yaml").is_file()


def test_malformed_model_output_engages_fallback_once_and_fails_cleanly(
    monkeypatch: Any, tmp_path: Path
) -> None:
    root = build_scenario("blank", tmp_path / "invalid").root
    invocation = _patch_conversation(
        monkeypatch,
        tmp_path,
        server_mode="invalid",
        fallback_mode="invalid",
    )
    answers = "\n".join(
        (
            "Build a CLI",
            "CLI tool",
            "active-development",
            "medium",
            "None",
            "None",
            "yes",
            "yes",
            "no",
            "standard",
            "test-first",
        )
    ) + "\n"

    result = _invoke_conversation(
        root,
        tmp_path / "invalid.sqlite3",
        run_id="invalid-conversation",
        answers=answers,
        extra=("--dry-run",),
    )

    assert result.exit_code == 2
    assert "fallback output" in result.output
    assert invocation.is_file()


def test_user_cancels_mid_conversation_leaving_resumable_paused_checkpoint(
    monkeypatch: Any, tmp_path: Path
) -> None:
    root = build_scenario("blank", tmp_path / "cancel").root
    checkpoint_path = tmp_path / "cancel.sqlite3"
    _patch_conversation(monkeypatch, tmp_path)

    result = _invoke_conversation(
        root,
        checkpoint_path,
        run_id="cancel-conversation",
        answers="Build a CLI\nCLI tool\n",
        extra=("--dry-run",),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload == {
        "run_id": "cancel-conversation",
        "stage": "interview",
        "status": "paused",
    }
    checkpoint = SqliteCheckpointStore(checkpoint_path).load("cancel-conversation")
    assert checkpoint.status is InitStatus.PAUSED
    assert checkpoint.stage is InitStage.INTERVIEW
    assert SqliteCheckpointStore(checkpoint_path).load_interview_progress(
        "cancel-conversation"
    ).answers == {
        "project.goal": "Build a CLI",
        "project.type": "CLI tool",
    }

    _patch_conversation(monkeypatch, tmp_path, server_mode="lost-thread")
    resumed = _invoke_conversation(
        root,
        checkpoint_path,
        run_id="cancel-conversation",
        answers="\n".join(
            (
                "active-development",
                "medium",
                "None",
                "None",
                "yes",
                "yes",
                "no",
                "standard",
                "test-first",
            )
        )
        + "\n",
        extra=("--resume", "--dry-run"),
    )
    assert resumed.exit_code == 0, resumed.output
    assert json.loads(resumed.stdout.splitlines()[-1])["status"] == "dry-run"
