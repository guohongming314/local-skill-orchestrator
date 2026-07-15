from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from vibe.cli import app
from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.models import AuditEvent
from vibe.persistence.repositories import AuditEventRepository

pytestmark = pytest.mark.validation

runner = CliRunner()


def _seed_event(
    factory: sessionmaker[Session],
    *,
    event_type: str,
    capability: str,
    summary: str,
    created_at: datetime,
    details: dict[str, str] | None = None,
) -> int:
    record = AuditEventRepository(factory).write(
        event_type=event_type,
        summary=summary,
        details={"capability_id": capability, **(details or {})},
    )
    with factory.begin() as session:
        session.execute(
            update(AuditEvent).where(AuditEvent.id == record.event_id).values(created_at=created_at)
        )
    return record.event_id


def _database(tmp_path: Path) -> tuple[Path, sessionmaker[Session]]:
    database = tmp_path / "state.sqlite3"
    command.upgrade(migration_config(database), "head")
    factory = sessionmaker(create_sqlite_engine(database), class_=Session, expire_on_commit=False)
    return database, factory


def test_seeded_events_produce_filtered_ordered_json_output(tmp_path: Path) -> None:
    database, factory = _database(tmp_path)
    later_id = _seed_event(
        factory,
        event_type="capability.install",
        capability="browser.testing",
        summary="Installed browser testing",
        created_at=datetime(2026, 7, 14, 12, 0),
    )
    earlier_id = _seed_event(
        factory,
        event_type="capability.approval",
        capability="browser.testing",
        summary="Approved browser testing",
        created_at=datetime(2026, 7, 14, 11, 0),
        details={"approval_level": "L2", "approved_by": "owner"},
    )
    _seed_event(
        factory,
        event_type="capability.install",
        capability="unrelated.capability",
        summary="Installed unrelated capability",
        created_at=datetime(2026, 7, 14, 10, 0),
    )

    result = runner.invoke(
        app,
        [
            "audit",
            "--database",
            str(database),
            "--capability",
            "browser.testing",
            "--from",
            "2026-07-14T10:30:00",
            "--to",
            "2026-07-14T12:30:00",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "1"
    assert [event["event_id"] for event in payload["events"]] == [earlier_id, later_id]
    assert [event["event_kind"] for event in payload["events"]] == [
        "capability.approval",
        "capability.install",
    ]
    assert payload["filters"] == {
        "capability": "browser.testing",
        "event_kind": None,
        "from_time": "2026-07-14T10:30:00",
        "to_time": "2026-07-14T12:30:00",
    }
    assert payload["findings"] == []


def test_event_kind_filter_renders_deterministic_human_table(tmp_path: Path) -> None:
    database, factory = _database(tmp_path)
    _seed_event(
        factory,
        event_type="capability.approval",
        capability="browser.testing",
        summary="Approved browser testing",
        created_at=datetime(2026, 7, 14, 11, 0),
    )
    _seed_event(
        factory,
        event_type="capability.install",
        capability="browser.testing",
        summary="Installed browser testing",
        created_at=datetime(2026, 7, 14, 12, 0),
    )

    result = runner.invoke(
        app,
        [
            "audit",
            "--database",
            str(database),
            "--event-kind",
            "capability.approval",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "capability.approval" in result.stdout
    assert "Approved browser testing" in result.stdout
    assert "capability.install" not in result.stdout
    assert "No integrity gaps found." in result.stdout


def test_install_without_matching_approval_is_flagged(tmp_path: Path) -> None:
    database, factory = _database(tmp_path)
    install_id = _seed_event(
        factory,
        event_type="capability.install",
        capability="browser.testing",
        summary="Installed browser testing",
        created_at=datetime(2026, 7, 14, 12, 0),
        details={"approval_level": "L2"},
    )

    result = runner.invoke(
        app,
        ["audit", "--database", str(database), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["findings"] == [
        {
            "code": "install-without-approval",
            "event_id": install_id,
            "capability_id": "browser.testing",
            "severity": "gap",
            "summary": "Install event has no earlier matching approval event.",
        }
    ]


def test_approval_before_filtered_window_still_satisfies_integrity(tmp_path: Path) -> None:
    database, factory = _database(tmp_path)
    _seed_event(
        factory,
        event_type="capability.approval",
        capability="browser.testing",
        summary="Approved browser testing",
        created_at=datetime(2026, 7, 13, 12, 0),
    )
    _seed_event(
        factory,
        event_type="capability.install",
        capability="browser.testing",
        summary="Installed browser testing",
        created_at=datetime(2026, 7, 14, 12, 0),
    )

    result = runner.invoke(
        app,
        [
            "audit",
            "--database",
            str(database),
            "--from",
            "2026-07-14T00:00:00",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["findings"] == []
