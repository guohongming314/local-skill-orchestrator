"""CLI entry point for transactional project-local capability installation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict
from rich.console import Console

from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.service import InventoryResult, InventoryService
from vibe.materialize.changeset import render_dry_run
from vibe.models.capability import CapabilityScope
from vibe.remote.install import InstallPackage, build_install_plan, execute_install
from vibe.remote.models import PermissionLevel, RemoteCandidate

console = Console()


class CandidateBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate: RemoteCandidate
    package: InstallPackage


def install_command(
    capability: Annotated[str, typer.Argument(help="Approved remote capability name.")],
    path: Annotated[Path, typer.Option("--path", help="Project root.")] = Path("."),
    candidate_file: Annotated[
        Path,
        typer.Option("--candidate-file", help="Approved candidate package bundle."),
    ] = Path("candidate.json"),
    approve: Annotated[
        bool,
        typer.Option("--approve", help="Explicitly approve this L1/L2 install."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Render the ChangeSet without writing."),
    ] = False,
) -> None:
    """Install one approved remote capability into the current project."""
    root = path.resolve()
    bundle = CandidateBundle.model_validate_json(candidate_file.read_text(encoding="utf-8"))
    if bundle.candidate.name != capability:
        console.print(
            f"Candidate name {bundle.candidate.name!r} does not match requested {capability!r}."
        )
        raise typer.Exit(code=2)
    plan = build_install_plan(root, bundle.candidate, bundle.package)
    if dry_run:
        console.print(render_dry_run(plan.changeset))
        return
    if plan.required_approval is PermissionLevel.L3:
        confirmation = typer.prompt(
            "L3 install requires item-specific approval; type the candidate reference"
        )
        approved = confirmation == plan.candidate.candidate_ref
    else:
        approved = approve
    if not approved:
        console.print(
            f"Explicit {plan.required_approval.value} approval is required; no changes made."
        )
        raise typer.Exit(code=2)
    result = execute_install(plan, approved=True, inventory_scan=_scan_project_inventory)
    console.print(
        f"Installed {capability} at {bundle.candidate.version}; "
        f"verified {len(result.inventory.capabilities)} inventory capabilities."
    )


def _scan_project_inventory(root: Path) -> InventoryResult:
    return InventoryService().scan(
        (
            AgentSkillAdapter(
                roots=(
                    SkillRoot(
                        path=root / ".agents" / "skills",
                        scope=CapabilityScope.PROJECT,
                    ),
                )
            ),
        )
    )
