from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from alembic import command
from pydantic import Field
from sqlalchemy.orm import Session, sessionmaker

from vibe.codex.exec_fallback import CodexExecFallback, StructuredResultError
from vibe.commands.spike_codex import SpikeResult, run_spike
from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.repositories import (
    AuditEventRepository,
    CodexThreadRepository,
    RunRepository,
    RunStatus,
)

FAKE_SERVER = Path(__file__).parents[1] / "fakes" / "fake_structured_app_server.py"
FAKE_EXEC = Path(__file__).parents[1] / "fakes" / "fake_codex_exec.py"


def app_command(mode: str, state_file: Path) -> tuple[str, ...]:
    return (sys.executable, str(FAKE_SERVER), mode, str(state_file))


def exec_fallback(mode: str, invocation_file: Path) -> CodexExecFallback:
    return CodexExecFallback(
        command=(sys.executable, str(FAKE_EXEC), mode, str(invocation_file))
    )


def repositories(
    database: Path,
) -> tuple[RunRepository, CodexThreadRepository, AuditEventRepository]:
    command.upgrade(migration_config(database), "head")
    factory = sessionmaker(create_sqlite_engine(database), class_=Session, expire_on_commit=False)
    return RunRepository(factory), CodexThreadRepository(factory), AuditEventRepository(factory)


@pytest.mark.anyio
async def test_spike_returns_validated_json_after_two_turns_and_persists_state(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    runs, threads, audit = repositories(database)
    invocation = tmp_path / "exec.json"

    result = await run_spike(
        cwd=tmp_path,
        graph_run_id="run-valid",
        repository_digest="digest-valid",
        app_server_command=app_command("structured-valid", tmp_path / "server.json"),
        exec_fallback=exec_fallback("valid", invocation),
        run_repository=runs,
        thread_repository=threads,
        audit_repository=audit,
    )

    assert result == SpikeResult(summary="validated", turn_count=2)
    assert runs.get("run-valid").status is RunStatus.COMPLETED
    assert threads.get_by_run_id("run-valid") is not None
    events = audit.list_for_run("run-valid")
    assert [event.event_type for event in events] == [
        "codex.turn.completed",
        "codex.turn.completed",
    ]
    assert not invocation.exists()
    assert all("validated" not in json.dumps(event.details) for event in events)


@pytest.mark.anyio
async def test_invalid_output_repairs_exactly_once_on_same_thread(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    runs, threads, audit = repositories(database)

    result = await run_spike(
        cwd=tmp_path,
        graph_run_id="run-repair",
        repository_digest="digest-repair",
        app_server_command=app_command("structured-repair", tmp_path / "server.json"),
        exec_fallback=exec_fallback("fail-if-called", tmp_path / "exec.json"),
        run_repository=runs,
        thread_repository=threads,
        audit_repository=audit,
    )

    assert result.summary == "repaired"
    state = json.loads((tmp_path / "server.json").read_text())
    assert state["turn_count"] == 3
    assert state["thread_ids"] == ["thread-1", "thread-1", "thread-1"]
    assert len(audit.list_for_run("run-repair")) == 3


@pytest.mark.anyio
async def test_second_invalid_output_falls_back_to_codex_exec_with_schema(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    runs, threads, audit = repositories(database)
    invocation = tmp_path / "exec.json"

    result = await run_spike(
        cwd=tmp_path,
        graph_run_id="run-fallback",
        repository_digest="digest-fallback",
        app_server_command=app_command("structured-invalid", tmp_path / "server.json"),
        exec_fallback=exec_fallback("valid", invocation),
        run_repository=runs,
        thread_repository=threads,
        audit_repository=audit,
    )

    assert result.summary == "fallback"
    recorded = json.loads(invocation.read_text())
    assert "--json" in recorded["argv"]
    assert "--output-schema" in recorded["argv"]
    assert recorded["schema"]["properties"]["summary"]["minLength"] == 1
    assert recorded["cwd"] == str(tmp_path.resolve())
    assert runs.get("run-fallback").status is RunStatus.COMPLETED


@pytest.mark.anyio
async def test_invalid_fallback_fails_clearly_and_marks_run_failed(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    runs, threads, audit = repositories(database)

    with pytest.raises(StructuredResultError, match="fallback output"):
        await run_spike(
            cwd=tmp_path,
            graph_run_id="run-failed",
            repository_digest="digest-failed",
            app_server_command=app_command("structured-invalid", tmp_path / "server.json"),
            exec_fallback=exec_fallback("invalid", tmp_path / "exec.json"),
            run_repository=runs,
            thread_repository=threads,
            audit_repository=audit,
        )

    failed = runs.get("run-failed")
    assert failed.status is RunStatus.FAILED
    assert failed.error_summary is not None
    assert "raw" not in failed.error_summary


@pytest.mark.anyio
async def test_exec_nonzero_reports_exit_code_and_bounded_stderr(tmp_path: Path) -> None:
    fallback = exec_fallback("crash", tmp_path / "exec.json")

    with pytest.raises(StructuredResultError, match="exit code 23") as captured:
        await fallback.run(
            prompt="return JSON",
            model_type=SpikeResult,
            cwd=tmp_path,
        )

    assert len(str(captured.value)) < 1200


class StrictResult(SpikeResult):
    summary: str = Field(min_length=10)
