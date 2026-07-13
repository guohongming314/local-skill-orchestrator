from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import inspect, text

from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.models import Base

EXPECTED_TABLES = {
    "alembic_version",
    "audit_events",
    "capability_verifications",
    "codex_threads",
    "inventory_cache",
    "runs",
    "user_trust_decisions",
}
FORBIDDEN_COLUMN_TERMS = {"password", "secret", "token", "credential", "api_key"}





def test_sqlite_engine_creates_parent_and_enables_safety_pragmas(tmp_path: Path) -> None:
    database = tmp_path / "nested" / "state.sqlite3"

    engine = create_sqlite_engine(database)

    assert database.parent.is_dir()
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        assert connection.scalar(text("PRAGMA busy_timeout")) == 5_000


def test_initial_migration_upgrades_and_downgrades_clean_database(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    config = migration_config(database)

    command.upgrade(config, "head")

    engine = create_sqlite_engine(database)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    assert set(Base.metadata.tables) == EXPECTED_TABLES - {"alembic_version"}

    command.downgrade(config, "base")

    assert inspect(engine).get_table_names() == ["alembic_version"]


def test_business_schema_has_no_secret_bearing_columns(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    command.upgrade(migration_config(database), "head")
    inspector = inspect(create_sqlite_engine(database))

    for table_name in EXPECTED_TABLES - {"alembic_version"}:
        column_names = {column["name"] for column in inspector.get_columns(table_name)}
        assert all(
            forbidden not in column_name
            for column_name in column_names
            for forbidden in FORBIDDEN_COLUMN_TERMS
        ), f"{table_name} contains a secret-bearing column: {sorted(column_names)}"


def test_run_schema_captures_recovery_identity_and_safe_errors(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    command.upgrade(migration_config(database), "head")
    inspector = inspect(create_sqlite_engine(database))

    run_columns = {column["name"] for column in inspector.get_columns("runs")}
    assert {
        "id",
        "status",
        "checkpoint_namespace",
        "resume_input_digest",
        "permission_state_digest",
        "error_summary",
    } <= run_columns
    thread_columns = {column["name"] for column in inspector.get_columns("codex_threads")}
    assert {"run_id", "codex_thread_id"} <= thread_columns
