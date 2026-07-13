import json
from pathlib import Path
from typing import Annotated

import typer

from vibe.models import (
    Blueprint,
    CapabilityManifest,
    ContextCapsule,
    RepositorySnapshot,
    ResolutionPlan,
    TaskPlan,
)
from vibe.models.base import VersionedModel

schema_app = typer.Typer(help="Export versioned project configuration schemas.")

SCHEMA_MODELS: dict[str, type[VersionedModel]] = {
    "blueprint": Blueprint,
    "capability-manifest": CapabilityManifest,
    "context-capsule": ContextCapsule,
    "repository-snapshot": RepositorySnapshot,
    "resolution-plan": ResolutionPlan,
    "task-plan": TaskPlan,
}


@schema_app.command("export")
def export_schemas(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Directory to receive JSON Schema files."),
    ],
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMA_MODELS.items():
        target = output / f"{name}.schema.json"
        document = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        target.write_text(document, encoding="utf-8")
    typer.echo(f"Exported {len(SCHEMA_MODELS)} schemas to {output}")
