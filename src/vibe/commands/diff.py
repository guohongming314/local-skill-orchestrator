"""Preview exact regenerated project configuration changes without writing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError

from vibe.commands.init import _project_changeset
from vibe.materialize.changeset import ChangeKind, ChangeOperation
from vibe.models.blueprint import Blueprint


def diff_command(
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Regenerate configuration in memory and report pending changes."""
    root = (path or Path.cwd()).resolve()
    try:
        blueprint = _load_blueprint(root)
        changeset = _project_changeset(root, blueprint)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError) as error:
        message = f"cannot regenerate project configuration: {type(error).__name__}"
        if json_output:
            typer.echo(
                json.dumps(
                    {"schema_version": "1", "status": "error", "error": message},
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        else:
            typer.echo(message, err=True)
        raise typer.Exit(2) from error

    changed = tuple(
        operation
        for operation in changeset.operations
        if operation.kind is not ChangeKind.UNCHANGED
    )
    status = "changes-pending" if changed else "current"
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "schema_version": "1",
                    "status": status,
                    "changes": [_change_payload(item) for item in changed],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        if not changed:
            typer.echo("Project configuration is current.")
        for operation in changed:
            typer.echo(f"{operation.kind.value.upper()} {operation.path}")
            typer.echo(
                f"  digest: {operation.before_digest[:12]} -> "
                f"{operation.after_digest[:12]}"
            )
    if changed:
        raise typer.Exit(1)


def _load_blueprint(root: Path) -> Blueprint:
    target = root / ".ai-project" / "blueprint.yaml"
    payload = yaml.safe_load(target.read_text(encoding="utf-8-sig"))
    return Blueprint.model_validate(payload)


def _change_payload(operation: ChangeOperation) -> dict[str, str]:
    return {
        "path": operation.path,
        "kind": operation.kind.value,
        "actual_digest": operation.before_digest,
        "expected_digest": operation.after_digest,
    }
