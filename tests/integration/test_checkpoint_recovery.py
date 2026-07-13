from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.repositories import CodexThreadRepository, RunRepository, RunStatus

WORKER = Path(__file__).parents[1] / "fakes" / "checkpoint_worker.py"


def worker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WORKER), *args], check=False, capture_output=True, text=True
    )


def repositories(database: Path) -> tuple[RunRepository, CodexThreadRepository]:
    command.upgrade(migration_config(database), "head")
    factory = sessionmaker(create_sqlite_engine(database), class_=Session, expire_on_commit=False)
    return RunRepository(factory), CodexThreadRepository(factory)


def test_graph_pauses_and_resumes_in_a_new_process(tmp_path: Path) -> None:
    business = tmp_path / "business.sqlite3"
    checkpoints = tmp_path / "checkpoints.sqlite3"
    started = worker(
        "start", str(business), str(checkpoints), "run-1", "codex-thread-9",
        "repo-digest", "permission-digest",
    )
    assert started.returncode == 0, started.stderr
    assert json.loads(started.stdout)["status"] == "paused"

    resumed = worker(
        "resume", str(business), str(checkpoints), "run-1",
        "repo-digest", "permission-digest",
    )
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout) == {
        "codex_thread_id": "codex-thread-9",
        "graph_run_id": "run-1",
        "status": "completed",
    }

    runs, threads = repositories(business)
    assert runs.get("run-1").status is RunStatus.COMPLETED
    thread = threads.get_by_run_id("run-1")
    assert thread is not None
    assert thread.codex_thread_id != thread.graph_run_id


def test_changed_repository_digest_rejects_direct_resume(tmp_path: Path) -> None:
    business = tmp_path / "business.sqlite3"
    checkpoints = tmp_path / "checkpoints.sqlite3"
    assert worker(
        "start", str(business), str(checkpoints), "run-2", "thread-2", "repo-a", "perm-a"
    ).returncode == 0

    resumed = worker(
        "resume", str(business), str(checkpoints), "run-2", "repo-b", "perm-a"
    )
    assert resumed.returncode == 2
    assert "repository digest changed" in resumed.stderr
    runs, _ = repositories(business)
    assert runs.get("run-2").status is RunStatus.PAUSED


def test_changed_permission_state_rejects_direct_resume(tmp_path: Path) -> None:
    business = tmp_path / "business.sqlite3"
    checkpoints = tmp_path / "checkpoints.sqlite3"
    assert worker(
        "start", str(business), str(checkpoints), "run-3", "thread-3", "repo-a", "perm-a"
    ).returncode == 0

    resumed = worker(
        "resume", str(business), str(checkpoints), "run-3", "repo-a", "perm-expanded"
    )
    assert resumed.returncode == 2
    assert "permission state changed" in resumed.stderr


def test_checkpoint_recovery_is_exposed_through_cli(tmp_path: Path) -> None:
    business = tmp_path / "business.sqlite3"
    checkpoints = tmp_path / "checkpoints.sqlite3"
    start = subprocess.run(
        [
            sys.executable, "-m", "vibe", "checkpoint-start",
            "--database", str(business), "--checkpoints", str(checkpoints),
            "--graph-run-id", "run-cli", "--codex-thread-id", "thread-cli",
            "--repository-digest", "repo-cli", "--permission-state-digest", "perm-cli",
        ],
        check=False, capture_output=True, text=True,
    )
    assert start.returncode == 0, start.stderr
    assert json.loads(start.stdout)["status"] == "paused"

    resume = subprocess.run(
        [
            sys.executable, "-m", "vibe", "checkpoint-resume",
            "--database", str(business), "--checkpoints", str(checkpoints),
            "--graph-run-id", "run-cli", "--repository-digest", "repo-cli",
            "--permission-state-digest", "perm-cli",
        ],
        check=False, capture_output=True, text=True,
    )
    assert resume.returncode == 0, resume.stderr
    assert json.loads(resume.stdout)["status"] == "completed"
