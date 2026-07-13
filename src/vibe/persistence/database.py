from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from platformdirs import user_state_path
from sqlalchemy import Engine, event
from sqlalchemy.engine import URL, create_engine

APPLICATION_NAME = "local-skill-orchestrator"
DATABASE_FILENAME = "state.sqlite3"
SQLITE_BUSY_TIMEOUT_MS = 5_000


def default_database_path() -> Path:
    """Return the platform-appropriate per-user database path."""
    return user_state_path(APPLICATION_NAME, appauthor=False) / DATABASE_FILENAME


def sqlite_url(path: Path) -> str:
    """Return a SQLAlchemy SQLite URL for an absolute filesystem path."""
    return URL.create("sqlite+pysqlite", database=str(path.resolve())).render_as_string(
        hide_password=False
    )


def migration_config(path: Path | None = None) -> Config:
    """Build an Alembic configuration that works from source and installed packages."""
    database = (path or default_database_path()).resolve()
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations")))
    config.set_main_option("sqlalchemy.url", sqlite_url(database))
    return config

def create_sqlite_engine(path: Path | None = None) -> Engine:
    """Create a SQLite engine with local-state safety pragmas enabled."""
    database = (path or default_database_path()).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(sqlite_url(database))

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()

    return engine
