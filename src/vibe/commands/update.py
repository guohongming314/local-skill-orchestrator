"""CLI entry point for transactional pinned capability upgrades."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console

from vibe.commands.install import CandidateBundle, _scan_project_inventory
from vibe.remote.install import build_install_plan, execute_install
from vibe.remote.models import PermissionLevel

console = Console()

_LEVEL_ORDER = {
    PermissionLevel.L0: 0,
    PermissionLevel.L1: 1,
    PermissionLevel.L2: 2,
    PermissionLevel.L3: 3,
    PermissionLevel.L4: 4,
}


def update_command(
    capability: Annotated[str, typer.Argument(help="Locked capability name to upgrade.")],
    path: Annotated[Path, typer.Option("--path", help="Project root.")] = Path("."),
    candidate_file: Annotated[
        Path,
        typer.Option(
            "--candidate-file",
            help="Cached verified candidate package bundle for the newer version.",
        ),
    ] = Path("candidate.json"),
    approve: Annotated[
        bool,
        typer.Option("--approve", help="Explicitly approve this capability upgrade."),
    ] = False,
    check: Annotated[
        bool,
        typer.Option("--check", help="List the available upgrade without writing."),
    ] = False,
    offline: Annotated[
        bool,
        typer.Option("--offline", help="Use only the cached candidate bundle."),
    ] = False,
) -> None:
    """Upgrade one pinned capability through the verified install transaction."""
    del offline  # Candidate bundles are local cache snapshots; this command never fetches.
    root = path.resolve()
    bundle = CandidateBundle.model_validate_json(candidate_file.read_text(encoding="utf-8"))
    if bundle.candidate.name != capability:
        console.print(
            f"Candidate name {bundle.candidate.name!r} does not match requested {capability!r}."
        )
        raise typer.Exit(code=2)

    current = _locked_provider(root, bundle.candidate.kind.value, capability)
    old_version = _required_text(current, "version")
    new_version = bundle.candidate.version
    if new_version is None or not _is_newer(new_version, old_version):
        console.print(f"No newer version for {capability}; locked at {old_version}.")
        return

    old_level = PermissionLevel(_required_text(current, "permission_level"))
    provenance = bundle.candidate.provenance
    if provenance is None:
        raise ValueError("update candidates require verified provenance")
    new_level = provenance.permission_level
    expanded = _LEVEL_ORDER[new_level] > _LEVEL_ORDER[old_level]
    permission_diff = f"{old_level.value} -> {new_level.value}"
    console.print(f"{capability}: {old_version} -> {new_version}; permissions {permission_diff}")
    if check:
        return

    plan = build_install_plan(
        root,
        bundle.candidate,
        bundle.package,
        replace_existing=True,
    )
    if plan.required_approval is PermissionLevel.L3:
        confirmation = typer.prompt(
            "L3 update requires item-specific re-approval; type the candidate reference"
        )
        approved = confirmation == plan.candidate.candidate_ref
    else:
        approved = approve
    if not approved:
        prefix = "Permission expansion requires re-approval" if expanded else "Approval required"
        console.print(f"{prefix} ({permission_diff}); no changes made.")
        raise typer.Exit(code=2)

    execute_install(plan, approved=True, inventory_scan=_scan_project_inventory)
    console.print(f"Updated {capability}: {old_version} -> {new_version}.")


def _locked_provider(root: Path, kind: str, capability: str) -> dict[str, Any]:
    prefixes = {
        "agent-skill": "skill",
        "cli-tool": "cli",
        "mcp-server": "mcp",
        "plugin": "plugin",
    }
    provider_id = f"{prefixes[kind]}.{capability}"
    lock_path = root / ".ai-project/capabilities.lock"
    try:
        payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ValueError(f"cannot read capability lockfile: {lock_path}") from error
    providers = payload.get("providers") if isinstance(payload, dict) else None
    if isinstance(providers, list):
        for provider in providers:
            if isinstance(provider, dict) and provider.get("provider_id") == provider_id:
                return provider
    raise ValueError(f"capability {capability!r} is not pinned in capabilities.lock")


def _required_text(provider: dict[str, Any], field: str) -> str:
    value = provider.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"locked provider is missing {field}")
    return value


def _is_newer(candidate: str, current: str) -> bool:
    def key(version: str) -> tuple[tuple[int, int | str], ...]:
        parts = re.findall(r"\d+|[A-Za-z]+", version)
        return tuple((0, int(part)) if part.isdigit() else (1, part.lower()) for part in parts)

    return key(candidate) > key(current)
