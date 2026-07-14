from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from vibe.workflows.checkpoints import SqliteCheckpointStore
from vibe.workflows.init_graph import InitializationGraph, InvalidTransition
from vibe.workflows.state import InitStage, InitStatus


def graph(path: Path) -> InitializationGraph:
    return InitializationGraph(SqliteCheckpointStore(path))


def test_normal_path_preserves_confirmed_state(tmp_path: Path) -> None:
    workflow = graph(tmp_path / "init.sqlite3")
    checkpoint = workflow.start("run-1", repository_digest="repo-v1")
    assert checkpoint.stage is InitStage.INSPECT
    assert checkpoint.status is InitStatus.RUNNING

    for current, following in pairwise(InitStage):
        assert checkpoint.stage is current
        checkpoint = workflow.advance(
            "run-1",
            following,
            confirmed={current.value: f"confirmed-{current.value}"},
        )

    completed = workflow.complete("run-1", confirmed={InitStage.VERIFY.value: "confirmed-verify"})
    assert completed.status is InitStatus.COMPLETED
    assert completed.confirmed == {stage.value: f"confirmed-{stage.value}" for stage in InitStage}


def test_invalid_transition_fails_before_side_effect(tmp_path: Path) -> None:
    workflow = graph(tmp_path / "init.sqlite3")
    workflow.start("run-2", repository_digest="repo-v1")
    effects: list[str] = []

    with pytest.raises(InvalidTransition, match="inspect -> model"):
        workflow.advance(
            "run-2",
            InitStage.MODEL,
            confirmed={"inspect": "unsafe"},
            side_effect=lambda: effects.append("ran"),
        )

    assert effects == []
    restored = workflow.load("run-2")
    assert restored.stage is InitStage.INSPECT
    assert restored.confirmed == {}


def test_cancel_and_retry_preserve_valid_state(tmp_path: Path) -> None:
    workflow = graph(tmp_path / "init.sqlite3")
    workflow.start("run-3", repository_digest="repo-v1")
    inventory = workflow.advance("run-3", InitStage.INVENTORY, confirmed={"inspect": "facts"})
    failed = workflow.fail("run-3", "inventory unavailable")
    assert failed.status is InitStatus.FAILED
    assert failed.stage is InitStage.INVENTORY

    retried = workflow.retry("run-3")
    assert retried.status is InitStatus.RUNNING
    assert retried.stage is inventory.stage
    assert retried.attempt == 2
    assert retried.confirmed == {"inspect": "facts"}

    cancelled = workflow.cancel("run-3", reason="user requested")
    assert cancelled.status is InitStatus.CANCELLED
    assert cancelled.confirmed == {"inspect": "facts"}
    with pytest.raises(InvalidTransition, match="cancelled"):
        workflow.advance("run-3", InitStage.INTERVIEW)


def test_checkpoint_resumes_in_a_new_process_owner(tmp_path: Path) -> None:
    path = tmp_path / "init.sqlite3"
    first_process = graph(path)
    first_process.start("run-4", repository_digest="repo-v1")
    first_process.advance("run-4", InitStage.INVENTORY, confirmed={"inspect": {"root": "project"}})
    first_process.pause("run-4")

    second_process = graph(path)
    resumed = second_process.resume("run-4", repository_digest="repo-v1")
    assert resumed.status is InitStatus.RUNNING
    assert resumed.stage is InitStage.INVENTORY
    assert resumed.confirmed == {"inspect": {"root": "project"}}


def test_resume_rejects_stale_repository_before_mutation(tmp_path: Path) -> None:
    path = tmp_path / "init.sqlite3"
    workflow = graph(path)
    workflow.start("run-5", repository_digest="repo-v1")
    paused = workflow.pause("run-5")

    with pytest.raises(InvalidTransition, match="repository digest changed"):
        graph(path).resume("run-5", repository_digest="repo-v2")

    assert graph(path).load("run-5") == paused


def test_paused_checkpoint_is_readable_by_a_fresh_python_process(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    path = tmp_path / "cross-process.sqlite3"
    workflow = graph(path)
    workflow.start("run-process", repository_digest="repo-v1")
    workflow.advance("run-process", InitStage.INVENTORY, confirmed={"inspect": "durable"})
    workflow.pause("run-process")

    script = """
import json
import sys
from pathlib import Path
from vibe.workflows.checkpoints import SqliteCheckpointStore
from vibe.workflows.init_graph import InitializationGraph
checkpoint = InitializationGraph(SqliteCheckpointStore(Path(sys.argv[1]))).resume(
    'run-process', repository_digest='repo-v1'
)
print(json.dumps({
    'stage': checkpoint.stage.value,
    'status': checkpoint.status.value,
    'confirmed': checkpoint.confirmed,
    'checkpoint_id': checkpoint.checkpoint_id,
}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["stage"] == "inventory"
    assert payload["status"] == "running"
    assert payload["confirmed"] == {"inspect": "durable"}
    assert payload["checkpoint_id"].startswith("init:run-process:")


def test_interview_progress_persists_thread_and_confirmed_answers(tmp_path: Path) -> None:
    store = SqliteCheckpointStore(tmp_path / "init.sqlite3")
    workflow = InitializationGraph(store)
    workflow.start("run-progress", repository_digest="repo-v1")
    workflow.advance("run-progress", InitStage.INVENTORY)
    workflow.advance("run-progress", InitStage.INTERVIEW)

    store.save_interview_progress(
        "run-progress",
        thread_id="thread-1",
        answers={"project.goal": "Ship safely"},
        provenance={"project.goal": "user-response"},
        locked_questions=frozenset(),
    )

    progress = store.load_interview_progress("run-progress")
    assert progress.thread_id == "thread-1"
    assert progress.answers == {"project.goal": "Ship safely"}
    assert progress.provenance == {"project.goal": "user-response"}
