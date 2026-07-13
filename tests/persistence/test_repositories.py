from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.repositories import (
    CodexThreadRepository,
    InvalidRunTransition,
    RunRepository,
    RunStatus,
)


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    database = tmp_path / "state.sqlite3"
    command.upgrade(migration_config(database), "head")
    return sessionmaker(create_sqlite_engine(database), expire_on_commit=False)


def test_run_lifecycle_and_recovery_identity_round_trip(
    session_factory: sessionmaker[Session],
) -> None:
    runs = RunRepository(session_factory)
    threads = CodexThreadRepository(session_factory)

    created = runs.create(
        graph_run_id="run-1",
        repository_digest="repository-1234",
        checkpoint_namespace="checkpoint-1",
        resume_input_digest="input-1234",
        permission_state_digest="permissions-1234",
    )
    running = runs.transition("run-1", RunStatus.RUNNING)
    paused = runs.transition("run-1", RunStatus.PAUSED)
    thread = threads.associate("run-1", "codex-thread-1")

    assert created.status is RunStatus.PENDING
    assert running.status is RunStatus.RUNNING
    assert paused.status is RunStatus.PAUSED
    assert paused.graph_run_id == "run-1"
    assert paused.checkpoint_namespace == "checkpoint-1"
    assert paused.resume_input_digest == "input-1234"
    assert paused.permission_state_digest == "permissions-1234"
    assert paused.created_at <= paused.updated_at
    assert thread.graph_run_id == "run-1"
    assert thread.codex_thread_id == "codex-thread-1"
    assert threads.get_by_run_id("run-1") == thread
    assert threads.get_by_thread_id("codex-thread-1") == thread


def test_failure_records_only_a_non_secret_summary(
    session_factory: sessionmaker[Session],
) -> None:
    runs = RunRepository(session_factory)
    runs.create(graph_run_id="run-1", repository_digest="repository-1234")
    runs.transition("run-1", RunStatus.RUNNING)

    failed = runs.transition(
        "run-1",
        RunStatus.FAILED,
        error_summary="Codex process exited before returning a response.",
    )

    assert failed.status is RunStatus.FAILED
    assert failed.error_summary == "Codex process exited before returning a response."


def test_invalid_transition_rolls_back_without_partial_write(
    session_factory: sessionmaker[Session],
) -> None:
    runs = RunRepository(session_factory)
    created = runs.create(graph_run_id="run-1", repository_digest="repository-1234")

    with pytest.raises(InvalidRunTransition, match=r"pending.*completed"):
        runs.transition(
            "run-1",
            RunStatus.COMPLETED,
            error_summary="must not persist",
        )

    persisted = runs.get("run-1")
    assert persisted == created
    assert persisted.error_summary is None


def test_thread_association_requires_an_existing_run(
    session_factory: sessionmaker[Session],
) -> None:
    threads = CodexThreadRepository(session_factory)

    with pytest.raises(LookupError, match="missing-run"):
        threads.associate("missing-run", "codex-thread-1")

    assert threads.get_by_thread_id("codex-thread-1") is None
