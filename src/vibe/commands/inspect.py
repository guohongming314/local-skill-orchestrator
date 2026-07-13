"""Repository inspection command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from vibe.inspect.commands import inspect_commands
from vibe.inspect.infrastructure import inspect_infrastructure
from vibe.inspect.instructions import inspect_instructions
from vibe.inspect.repository import inspect_repository
from vibe.inspect.stack import inspect_stack
from vibe.models.repository import RepositoryFact, RepositorySnapshot


def inspect_command(
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect deterministic repository facts without model interaction."""
    target = (path or Path.cwd()).resolve()
    try:
        snapshot = _complete_snapshot(target)
    except (OSError, RuntimeError, ValueError) as exc:
        typer.echo(f"inspection failed for {target}: {exc}", err=True)
        raise typer.Exit(2) from exc
    if json_output:
        typer.echo(
            json.dumps(
                snapshot.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    typer.echo(f"Repository: {snapshot.root}")
    typer.echo(f"Source digest: {snapshot.source_digest}")
    typer.echo(f"Empty: {str(snapshot.is_empty).lower()}")
    for fact in snapshot.facts:
        value = "unknown" if fact.value is None else _display_value(fact)
        typer.echo(f"[{fact.confidence.value}] {fact.key}: {value}")


def _complete_snapshot(path: Path) -> RepositorySnapshot:
    base = inspect_repository(path)
    facts = (
        *base.facts,
        *inspect_stack(base.root),
        *inspect_commands(base.root),
        *inspect_infrastructure(base.root),
        *inspect_instructions(base.root),
    )
    return base.model_copy(update={"facts": tuple(sorted(facts, key=lambda fact: fact.key))})


def _display_value(fact: RepositoryFact) -> str:
    if isinstance(fact.value, list):
        return ", ".join(fact.value)
    return str(fact.value)
