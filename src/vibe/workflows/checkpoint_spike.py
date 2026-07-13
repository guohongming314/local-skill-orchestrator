"""Durable pause/resume spike using LangGraph's SQLite checkpointer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from vibe.persistence.repositories import CodexThreadRepository, RunRepository, RunStatus

_CHECKPOINT_NAMESPACE = "checkpoint-spike-v1"


class CheckpointSpikeError(RuntimeError):
    """Base error for checkpoint recovery failures."""


class StaleCheckpointError(CheckpointSpikeError):
    """Raised when persisted safety inputs no longer match resume inputs."""


class CheckpointStateError(CheckpointSpikeError):
    """Raised when persisted business or graph state cannot be resumed safely."""


class SpikeState(TypedDict):
    graph_run_id: str
    codex_thread_id: str
    status: str
    approval: NotRequired[str]


def _approval_node(state: SpikeState) -> dict[str, str]:
    approval = interrupt(
        {
            "kind": "checkpoint-spike-approval",
            "graph_run_id": state["graph_run_id"],
        }
    )
    return {"approval": str(approval), "status": "completed"}


def _graph(checkpointer: SqliteSaver) -> Any:
    builder = StateGraph(SpikeState)
    builder.add_node("approval", _approval_node)
    builder.add_edge(START, "approval")
    builder.add_edge("approval", END)
    return builder.compile(checkpointer=checkpointer)


class CheckpointSpike:
    """Start and recover one minimal durable graph around a Codex thread identity."""

    def __init__(
        self,
        *,
        checkpoint_path: Path,
        runs: RunRepository,
        threads: CodexThreadRepository,
    ) -> None:
        self._checkpoint_path = checkpoint_path
        self._runs = runs
        self._threads = threads

    def start(
        self,
        *,
        graph_run_id: str,
        codex_thread_id: str,
        repository_digest: str,
        permission_state_digest: str,
    ) -> dict[str, str]:
        """Persist identities and pause a new graph at its approval interrupt."""
        if graph_run_id == codex_thread_id:
            raise CheckpointStateError("Graph Run ID and Codex Thread ID must be distinct")
        self._runs.create(
            graph_run_id=graph_run_id,
            repository_digest=repository_digest,
            checkpoint_namespace=_CHECKPOINT_NAMESPACE,
            resume_input_digest=repository_digest,
            permission_state_digest=permission_state_digest,
        )
        self._threads.associate(graph_run_id, codex_thread_id)
        self._runs.transition(graph_run_id, RunStatus.RUNNING)

        with SqliteSaver.from_conn_string(str(self._checkpoint_path)) as checkpointer:
            graph = _graph(checkpointer)
            result = graph.invoke(
                {
                    "graph_run_id": graph_run_id,
                    "codex_thread_id": codex_thread_id,
                    "status": "running",
                },
                self._config(graph_run_id),
            )
        if "__interrupt__" not in cast(dict[str, object], result):
            self._fail_running(graph_run_id, "graph did not pause at the approval interrupt")
            raise CheckpointStateError("graph did not pause at the approval interrupt")
        self._runs.transition(graph_run_id, RunStatus.PAUSED)
        return {
            "graph_run_id": graph_run_id,
            "codex_thread_id": codex_thread_id,
            "status": "paused",
        }

    def resume(
        self,
        *,
        graph_run_id: str,
        repository_digest: str,
        permission_state_digest: str,
    ) -> dict[str, str]:
        """Revalidate safety inputs and resume the checkpoint in a new process."""
        run = self._runs.get(graph_run_id)
        if run.status is not RunStatus.PAUSED:
            raise CheckpointStateError(
                f"run {graph_run_id!r} is {run.status.value}, not paused"
            )
        if (
            repository_digest != run.repository_digest
            or repository_digest != run.resume_input_digest
        ):
            raise StaleCheckpointError("repository digest changed; direct resume rejected")
        if permission_state_digest != run.permission_state_digest:
            raise StaleCheckpointError("permission state changed; direct resume rejected")
        if run.checkpoint_namespace != _CHECKPOINT_NAMESPACE:
            raise CheckpointStateError("checkpoint namespace is missing or unsupported")
        thread = self._threads.get_by_run_id(graph_run_id)
        if thread is None:
            raise CheckpointStateError("Codex thread association is missing")

        self._runs.transition(graph_run_id, RunStatus.RUNNING)
        try:
            with SqliteSaver.from_conn_string(str(self._checkpoint_path)) as checkpointer:
                graph = _graph(checkpointer)
                raw = cast(
                    dict[str, object],
                    graph.invoke(Command(resume="approved"), self._config(graph_run_id)),
                )
            if raw.get("status") != "completed":
                raise CheckpointStateError("checkpoint did not complete after resume")
            if raw.get("graph_run_id") != graph_run_id:
                raise CheckpointStateError("checkpoint Graph Run ID does not match")
            if raw.get("codex_thread_id") != thread.codex_thread_id:
                raise CheckpointStateError("checkpoint Codex Thread ID does not match")
        except BaseException as exc:
            self._fail_running(graph_run_id, f"{type(exc).__name__}: checkpoint resume failed")
            raise
        self._runs.transition(graph_run_id, RunStatus.COMPLETED)
        return {
            "graph_run_id": graph_run_id,
            "codex_thread_id": thread.codex_thread_id,
            "status": "completed",
        }

    @staticmethod
    def _config(graph_run_id: str) -> dict[str, dict[str, str]]:
        return {
            "configurable": {
                "thread_id": graph_run_id,
                "checkpoint_ns": _CHECKPOINT_NAMESPACE,
            }
        }

    def _fail_running(self, graph_run_id: str, summary: str) -> None:
        if self._runs.get(graph_run_id).status is RunStatus.RUNNING:
            self._runs.transition(graph_run_id, RunStatus.FAILED, error_summary=summary)
