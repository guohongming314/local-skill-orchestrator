"""Apply versioned YAML migrations through the atomic ChangeSet writer."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml

from vibe.materialize.changeset import ChangeProposal, build_changeset
from vibe.materialize.ownership import FileOwnership
from vibe.materialize.writer import apply_changeset
from vibe.migrations.registry import default_registry, discover_artifacts, dump_yaml

_PROVENANCE_PATH = ".ai-project/migration-provenance.yaml"


def migrate_command(
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Upgrade supported YAML artifacts deterministically and atomically."""
    root = (path or Path.cwd()).resolve()
    proposals: list[ChangeProposal] = []
    previews: list[str] = []
    records: list[dict[str, str]] = []

    for artifact in discover_artifacts(root):
        result = default_registry.migrate(artifact.kind, artifact.payload)
        if not result.provenance:
            continue
        before = artifact.path.read_text(encoding="utf-8-sig")
        after = dump_yaml(result.payload)
        proposals.append(
            ChangeProposal(
                path=artifact.relative_path,
                desired_content=after,
                ownership=FileOwnership.OWNED,
                source="versioned schema migration",
                reason=f"schema_version {result.from_version} -> {result.to_version}",
            )
        )
        previews.append(_yaml_diff(artifact.relative_path, before, after))
        records.append(
            {
                "path": artifact.relative_path,
                "kind": artifact.kind.value,
                "from_version": result.from_version,
                "to_version": result.to_version,
                "digest_before": result.provenance[0].digest_before,
                "digest_after": result.provenance[-1].digest_after,
            }
        )

    if not proposals:
        typer.echo("No migrations required.")
        return

    history_target = root / _PROVENANCE_PATH
    history_before = (
        history_target.read_text(encoding="utf-8-sig")
        if history_target.is_file()
        else ""
    )
    history = _load_history(root)
    history["migrations"].extend(records)
    history_after = dump_yaml(history)
    previews.append(_yaml_diff(_PROVENANCE_PATH, history_before, history_after))
    proposals.append(
        ChangeProposal(
            path=_PROVENANCE_PATH,
            desired_content=history_after,
            ownership=FileOwnership.OWNED,
            source="versioned schema migration",
            reason="record migration provenance",
        )
    )
    changeset = build_changeset(root, tuple(proposals))
    if dry_run:
        typer.echo("\n".join(previews), nl=False)
        return
    apply_result = apply_changeset(changeset)
    typer.echo(f"Applied migration ChangeSet {apply_result.changeset_digest}")
    for applied in apply_result.applied_paths:
        typer.echo(f"  {applied}")


def _load_history(root: Path) -> dict[str, Any]:
    target = root / _PROVENANCE_PATH
    if not target.is_file():
        return {"schema_version": "1", "migrations": []}
    payload = yaml.safe_load(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("migrations"), list):
        raise ValueError(f"invalid migration provenance file: {target}")
    return {"schema_version": "1", "migrations": list(payload["migrations"])}


def _yaml_diff(relative: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{relative} (before)",
            tofile=f"{relative} (after)",
        )
    )
