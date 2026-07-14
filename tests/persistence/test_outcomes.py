from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from vibe.models.outcome import TaskOutcome
from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.repositories import AuditEventRepository, TaskOutcomeRepository


def outcome() -> TaskOutcome:
    return TaskOutcome(
        task_type="bug-fix",
        workflow="standard",
        capabilities_used=("code-graph-analysis", "systematic-debugging"),
        verification_passed=True,
        user_rework=False,
        unused_recommendations=("project-memory",),
    )


def test_outcome_round_trips_through_published_schema() -> None:
    original = outcome()

    restored = TaskOutcome.model_validate_json(original.model_dump_json())
    schema = TaskOutcome.model_json_schema()

    assert restored == original
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "schema_version",
        "task_type",
        "workflow",
        "capabilities_used",
        "verification_passed",
        "user_rework",
        "unused_recommendations",
    }


@pytest.mark.parametrize("field", ["code_content", "conversation_text", "secret"])
def test_outcome_rejects_forbidden_fields(field: str) -> None:
    payload = outcome().model_dump(mode="json")
    payload[field] = "must not be stored"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TaskOutcome.model_validate(payload)


def test_outcome_survives_database_reopen_and_is_appended_to_audit_trail(
    tmp_path: Path,
) -> None:
    database = tmp_path / "state.sqlite3"
    command.upgrade(migration_config(database), "head")
    first_factory = sessionmaker(
        create_sqlite_engine(database), class_=Session, expire_on_commit=False
    )

    stored = TaskOutcomeRepository(first_factory).record("task-127", outcome())

    reopened_factory = sessionmaker(
        create_sqlite_engine(database), class_=Session, expire_on_commit=False
    )
    restored = TaskOutcomeRepository(reopened_factory).get("task-127")
    events = AuditEventRepository(reopened_factory).list_for_task("task-127")

    assert restored == stored
    assert restored.outcome == outcome()
    assert len(events) == 1
    assert events[0].event_type == "task.outcome.recorded"
    assert events[0].redacted is True
    assert events[0].details == outcome().model_dump(mode="json")
