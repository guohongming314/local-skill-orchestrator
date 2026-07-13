from __future__ import annotations

import json
import sys
from pathlib import Path

from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.repositories import CodexThreadRepository, RunRepository
from vibe.workflows.checkpoint_spike import CheckpointSpike, StaleCheckpointError


def main() -> None:
    action, business_raw, checkpoint_raw, run_id, *values = sys.argv[1:]
    business = Path(business_raw)
    command.upgrade(migration_config(business), "head")
    factory = sessionmaker(create_sqlite_engine(business), class_=Session, expire_on_commit=False)
    spike = CheckpointSpike(
        checkpoint_path=Path(checkpoint_raw),
        runs=RunRepository(factory),
        threads=CodexThreadRepository(factory),
    )
    try:
        if action == "start":
            thread_id, repository_digest, permission_digest = values
            result = spike.start(
                graph_run_id=run_id,
                codex_thread_id=thread_id,
                repository_digest=repository_digest,
                permission_state_digest=permission_digest,
            )
        else:
            repository_digest, permission_digest = values
            result = spike.resume(
                graph_run_id=run_id,
                repository_digest=repository_digest,
                permission_state_digest=permission_digest,
            )
    except StaleCheckpointError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
