"""Durable checkpoint storage owned by initialization workflows."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from vibe.workflows.state import InitCheckpoint, InitStage, InitStatus


class CheckpointNotFound(LookupError):
    """Raised when a workflow checkpoint does not exist."""


class CheckpointConflict(RuntimeError):
    """Raised when a stale owner attempts to replace a checkpoint."""


@dataclass(frozen=True)
class InterviewProgress:
    """Additive conversation state associated with one graph run."""

    thread_id: str | None
    answers: dict[str, str]
    provenance: dict[str, str]
    locked_questions: frozenset[str]


class SqliteCheckpointStore:
    """Persist workflow snapshots in a process-independent SQLite database."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vibe_init_checkpoints (
                    run_id TEXT PRIMARY KEY,
                    checkpoint_id TEXT NOT NULL UNIQUE,
                    repository_digest TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confirmed_json TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    revision INTEGER NOT NULL,
                    error TEXT,
                    cancellation_reason TEXT
                )
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(vibe_init_checkpoints)")
            }
            additions = {
                "codex_thread_id": "TEXT",
                "interview_answers_json": "TEXT NOT NULL DEFAULT '{}'",
                "interview_provenance_json": "TEXT NOT NULL DEFAULT '{}'",
                "interview_locked_json": "TEXT NOT NULL DEFAULT '[]'",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE vibe_init_checkpoints ADD COLUMN {name} {definition}"
                    )

    def save_interview_progress(
        self,
        run_id: str,
        *,
        thread_id: str | None,
        answers: dict[str, str],
        provenance: dict[str, str],
        locked_questions: frozenset[str],
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE vibe_init_checkpoints
                   SET codex_thread_id = ?, interview_answers_json = ?,
                       interview_provenance_json = ?, interview_locked_json = ?
                   WHERE run_id = ?""",
                (
                    thread_id,
                    self._encode(answers),
                    self._encode(provenance),
                    self._encode(sorted(locked_questions)),
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise CheckpointNotFound(f"checkpoint for run {run_id!r} does not exist")

    def load_interview_progress(self, run_id: str) -> InterviewProgress:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT codex_thread_id, interview_answers_json,
                          interview_provenance_json, interview_locked_json
                   FROM vibe_init_checkpoints WHERE run_id = ?""",
                (run_id,),
            ).fetchone()
        if row is None:
            raise CheckpointNotFound(f"checkpoint for run {run_id!r} does not exist")
        return InterviewProgress(
            thread_id=cast(str | None, row[0]),
            answers=cast(dict[str, str], json.loads(cast(str, row[1]))),
            provenance=cast(dict[str, str], json.loads(cast(str, row[2]))),
            locked_questions=frozenset(cast(list[str], json.loads(cast(str, row[3])))),
        )

    def create(self, checkpoint: InitCheckpoint) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO vibe_init_checkpoints
                       (run_id, checkpoint_id, repository_digest, stage, status,
                        confirmed_json, attempt, revision, error, cancellation_reason)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    self._values(checkpoint),
                )
        except sqlite3.IntegrityError as exc:
            raise CheckpointConflict(
                f"checkpoint for run {checkpoint.run_id!r} already exists"
            ) from exc

    def load(self, run_id: str) -> InitCheckpoint:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT checkpoint_id, repository_digest, stage, status,
                          confirmed_json, attempt, revision, error, cancellation_reason
                   FROM vibe_init_checkpoints WHERE run_id = ?""",
                (run_id,),
            ).fetchone()
        if row is None:
            raise CheckpointNotFound(f"checkpoint for run {run_id!r} does not exist")
        confirmed = cast(dict[str, Any], json.loads(cast(str, row[4])))
        return InitCheckpoint(
            checkpoint_id=cast(str, row[0]),
            run_id=run_id,
            repository_digest=cast(str, row[1]),
            stage=InitStage(cast(str, row[2])),
            status=InitStatus(cast(str, row[3])),
            confirmed=confirmed,
            attempt=cast(int, row[5]),
            revision=cast(int, row[6]),
            error=cast(str | None, row[7]),
            cancellation_reason=cast(str | None, row[8]),
        )

    def replace(self, previous: InitCheckpoint, current: InitCheckpoint) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE vibe_init_checkpoints
                   SET checkpoint_id = ?, repository_digest = ?, stage = ?, status = ?,
                       confirmed_json = ?, attempt = ?, revision = ?, error = ?,
                       cancellation_reason = ?
                   WHERE run_id = ? AND revision = ?""",
                (
                    current.checkpoint_id,
                    current.repository_digest,
                    current.stage.value,
                    current.status.value,
                    self._encode(current.confirmed),
                    current.attempt,
                    current.revision,
                    current.error,
                    current.cancellation_reason,
                    current.run_id,
                    previous.revision,
                ),
            )
            if cursor.rowcount != 1:
                raise CheckpointConflict(
                    f"checkpoint for run {current.run_id!r} changed concurrently"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @classmethod
    def _values(cls, checkpoint: InitCheckpoint) -> tuple[object, ...]:
        return (
            checkpoint.run_id,
            checkpoint.checkpoint_id,
            checkpoint.repository_digest,
            checkpoint.stage.value,
            checkpoint.status.value,
            cls._encode(checkpoint.confirmed),
            checkpoint.attempt,
            checkpoint.revision,
            checkpoint.error,
            checkpoint.cancellation_reason,
        )

    @staticmethod
    def _encode(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
