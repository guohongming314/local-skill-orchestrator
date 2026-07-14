"""CLI entry point for reversing recorded capability install transactions."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Any

import typer
from alembic import command
from rich.console import Console
from sqlalchemy.orm import Session, sessionmaker

from vibe.commands.install import _scan_project_inventory
from vibe.materialize.changeset import ChangeProposal, build_changeset
from vibe.materialize.ownership import FileOwnership
from vibe.materialize.writer import apply_changeset
from vibe.persistence.database import create_sqlite_engine, default_database_path, migration_config
from vibe.persistence.repositories import AuditEventRepository

console = Console()
_TRANSACTION_ROOT = ".ai-project/install-transactions"


class UninstallTransactionError(RuntimeError):
    """A requested capability has no valid reversible install transaction."""


def uninstall_command(
    capability: Annotated[str, typer.Argument(help="Installed capability name.")],
    path: Annotated[Path, typer.Option("--path", help="Project root.")] = Path("."),
) -> None:
    """Reverse one recorded project-local install transaction."""
    root = path.resolve()
    transaction_path, transaction = _load_transaction(root, capability)
    provider_id = str(transaction["provider_id"])
    before = transaction["before"]
    assert isinstance(before, dict)

    proposals = tuple(
        ChangeProposal(
            path=relative,
            desired_content=content,
            ownership=FileOwnership.OWNED,
            source=f"uninstall:{provider_id}",
            reason=f"reverse recorded install transaction for {capability}",
        )
        for relative, content in sorted(before.items())
        if isinstance(relative, str) and (content is None or isinstance(content, str))
    )
    changeset = build_changeset(root, proposals)

    with tempfile.TemporaryDirectory(prefix="vibe-uninstall-") as temporary:
        staged_root = Path(temporary) / "project"
        shutil.copytree(root, staged_root, ignore=shutil.ignore_patterns(".git"))
        staged = build_changeset(
            staged_root,
            tuple(
                ChangeProposal(
                    path=operation.path,
                    desired_content=operation.after_content,
                    ownership=operation.ownership,
                    source=operation.source,
                    reason=operation.reason,
                )
                for operation in changeset.operations
            ),
        )
        apply_changeset(staged)
        inventory = _scan_project_inventory(staged_root)
        if any(item.manifest.capability_id == provider_id for item in inventory.capabilities):
            raise UninstallTransactionError(
                f"inventory still resolves {provider_id!r} after staged uninstall"
            )

    result = apply_changeset(changeset)
    _record_audit(root, capability, provider_id, transaction_path.relative_to(root).as_posix())
    console.print(f"Uninstalled {capability}; restored {len(result.applied_paths)} paths.")


def _load_transaction(root: Path, capability: str) -> tuple[Path, dict[str, Any]]:
    directory = root / _TRANSACTION_ROOT
    matches: list[tuple[Path, dict[str, Any]]] = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(payload, dict)
                and payload.get("schema_version") == "1"
                and payload.get("capability") == capability
                and isinstance(payload.get("provider_id"), str)
                and isinstance(payload.get("before"), dict)
            ):
                matches.append((path, payload))
    if len(matches) != 1:
        raise UninstallTransactionError(
            f"expected one recorded install transaction for {capability!r}, found {len(matches)}"
        )
    return matches[0]


def _record_audit(
    root: Path, capability: str, provider_id: str, transaction_path: str
) -> None:
    database = default_database_path().resolve()
    if database.is_relative_to(root):
        database = Path(tempfile.gettempdir()) / "local-skill-orchestrator-audit.sqlite3"
    engine = create_sqlite_engine(database)
    command.upgrade(migration_config(database), "head")
    factory = sessionmaker(engine, class_=Session, expire_on_commit=False)
    AuditEventRepository(factory).write(
        event_type="capability.uninstall",
        summary=f"Uninstalled capability {capability}",
        details={
            "capability": capability,
            "provider_id": provider_id,
            "transaction_path": transaction_path,
        },
    )
