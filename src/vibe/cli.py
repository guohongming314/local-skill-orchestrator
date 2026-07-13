from typing import Annotated

import typer
from rich.console import Console

from vibe import __version__
from vibe.commands.schema import schema_app
from vibe.commands.spike_codex import checkpoint_resume, checkpoint_start, spike_codex

app = typer.Typer(
    name="vibe",
    help="Bootstrap and govern project-local AI development capabilities.",
    no_args_is_help=True,
)
console = Console()
app.add_typer(schema_app, name="schema")
app.command("spike-codex")(spike_codex)
app.command("checkpoint-start")(checkpoint_start)
app.command("checkpoint-resume")(checkpoint_resume)


def version_callback(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit


@app.callback()
def root(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """Run the local Skill Orchestrator control plane."""


def main() -> None:
    app()
