"""Codex app-server end-to-end structured-result spike."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Annotated

import anyio
import typer
from alembic import command
from pydantic import Field
from sqlalchemy.orm import Session, sessionmaker

from vibe.codex.app_server import CodexAppServerClient, CodexTurnResult, agent_message_text
from vibe.codex.exec_fallback import (
    CodexExecFallback,
    StructuredResultError,
    validate_structured_result,
)
from vibe.codex.jsonrpc import JsonRpcSubprocessClient
from vibe.codex.protocol import JsonObject
from vibe.models.base import VersionedModel
from vibe.persistence.database import create_sqlite_engine, default_database_path, migration_config
from vibe.persistence.repositories import (
    AuditEventRepository,
    CodexThreadRepository,
    RunRepository,
    RunStatus,
)


class SpikeResult(VersionedModel):
    """Schema returned by the protocol spike."""

    summary: str = Field(min_length=1)
    turn_count: int = Field(ge=2)


async def run_spike(
    *,
    cwd: Path,
    graph_run_id: str,
    repository_digest: str,
    app_server_command: Sequence[str],
    exec_fallback: CodexExecFallback,
    run_repository: RunRepository,
    thread_repository: CodexThreadRepository,
    audit_repository: AuditEventRepository,
    timeout: float = 300.0,
) -> SpikeResult:
    """Execute two primary turns, one repair at most, then an exec fallback."""
    run_repository.create(graph_run_id=graph_run_id, repository_digest=repository_digest)
    run_repository.transition(graph_run_id, RunStatus.RUNNING)
    try:
        async with JsonRpcSubprocessClient(app_server_command) as transport:
            client = CodexAppServerClient(transport)
            await client.initialize()
            thread = await client.start_thread(cwd=cwd)
            thread_repository.associate(graph_run_id, thread.id)
            await _recorded_turn(
                client,
                thread.id,
                "Establish context for the structured-result protocol spike.",
                graph_run_id,
                audit_repository,
                timeout=timeout,
            )
            result_turn = await _recorded_turn(
                client,
                thread.id,
                "Return the final result as JSON matching the supplied schema.",
                graph_run_id,
                audit_repository,
                timeout=timeout,
                output_schema=SpikeResult.model_json_schema(),
            )
            try:
                result = validate_structured_result(
                    agent_message_text(result_turn), SpikeResult, source="app-server output"
                )
            except StructuredResultError:
                repair_turn = await _recorded_turn(
                    client,
                    thread.id,
                    "Repair the previous response once. Return only schema-valid JSON.",
                    graph_run_id,
                    audit_repository,
                    timeout=timeout,
                    output_schema=SpikeResult.model_json_schema(),
                )
                try:
                    result = validate_structured_result(
                        agent_message_text(repair_turn), SpikeResult, source="repair output"
                    )
                except StructuredResultError:
                    result = await exec_fallback.run(
                        prompt="Return the protocol spike result as schema-valid JSON.",
                        model_type=SpikeResult,
                        cwd=cwd,
                    )
        run_repository.transition(graph_run_id, RunStatus.COMPLETED)
        return result
    except BaseException as exc:
        current = run_repository.get(graph_run_id)
        if current.status is RunStatus.RUNNING:
            run_repository.transition(
                graph_run_id,
                RunStatus.FAILED,
                error_summary=f"{type(exc).__name__}: structured Codex spike failed",
            )
        raise


async def _recorded_turn(
    client: CodexAppServerClient,
    thread_id: str,
    prompt: str,
    graph_run_id: str,
    audit_repository: AuditEventRepository,
    *,
    timeout: float,
    output_schema: JsonObject | None = None,
) -> CodexTurnResult:
    result = await client.run_turn(
        thread_id, prompt, timeout=timeout, output_schema=output_schema
    )
    audit_repository.write(
        event_type="codex.turn.completed",
        summary="Codex turn completed",
        details={
            "turn_id": result.turn.id,
            "thread_id": result.turn.thread_id,
            "status": result.turn.status.value,
        },
        run_id=graph_run_id,
    )
    return result


def spike_codex(
    cwd: Annotated[
        Path | None, typer.Option("--cwd", exists=True, file_okay=False)
    ] = None,
    database: Annotated[Path | None, typer.Option("--database")] = None,
) -> None:
    """Run two Codex app-server turns and print a schema-validated JSON result."""
    database_path = database or default_database_path()
    command.upgrade(migration_config(database_path), "head")
    factory = sessionmaker(
        create_sqlite_engine(database_path), class_=Session, expire_on_commit=False
    )
    resolved = (cwd or Path.cwd()).resolve()
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()
    result = anyio.run(
        partial(
            run_spike,
            cwd=resolved,
            graph_run_id=str(uuid.uuid4()),
            repository_digest=digest,
            app_server_command=("codex", "app-server"),
            exec_fallback=CodexExecFallback(),
            run_repository=RunRepository(factory),
            thread_repository=CodexThreadRepository(factory),
            audit_repository=AuditEventRepository(factory),
        )
    )
    typer.echo(json.dumps(result.model_dump(mode="json"), sort_keys=True))
