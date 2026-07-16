"""List, explain, and diagnose normalized local capabilities."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.adapters.base import AdapterScanResult
from vibe.inventory.adapters.cli_tool import CliToolAdapter, CliToolSpec
from vibe.inventory.adapters.codex_hook import CodexHookAdapter
from vibe.inventory.adapters.codex_mcp import CodexMcpAdapter
from vibe.inventory.adapters.codex_plugin import CodexPluginAdapter
from vibe.inventory.service import InventoryDiagnostic, InventoryResult, InventoryService
from vibe.models.capability import CapabilityScope
from vibe.persistence.database import create_sqlite_engine, default_database_path, migration_config
from vibe.persistence.repositories import (
    CapabilityVerificationRepository,
    InventoryCacheRepository,
    JsonValue,
)

capabilities_app = typer.Typer(help="Inspect normalized local capabilities.")

ConfigOption = Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)]
PluginsOption = Annotated[Path, typer.Option("--plugins-root", exists=True, file_okay=False)]
DatabaseOption = Annotated[Path | None, typer.Option("--database")]
JsonOption = Annotated[bool, typer.Option("--json")]
ProjectOption = Annotated[Path | None, typer.Option("--project", file_okay=False)]
UserSkillsOption = Annotated[Path | None, typer.Option("--user-skills", file_okay=False)]


@capabilities_app.command("list")
def list_capabilities(
    config: ConfigOption,
    plugins_root: PluginsOption,
    database: DatabaseOption = None,
    json_output: JsonOption = False,
    project: ProjectOption = None,
    user_skills: UserSkillsOption = None,
) -> None:
    """List capabilities with provenance, permissions, compatibility, and status."""
    inventory = _scan_and_persist(config, plugins_root, database, project, user_skills)
    payload = {"capabilities": [_public_capability(item) for item in inventory.capabilities]}
    _emit(payload, json_output)


@capabilities_app.command("explain")
def explain_capability(
    capability_id: str,
    config: ConfigOption,
    plugins_root: PluginsOption,
    database: DatabaseOption = None,
    json_output: JsonOption = False,
    project: ProjectOption = None,
    user_skills: UserSkillsOption = None,
) -> None:
    """Explain one capability and its adapter provenance."""
    inventory = _scan_and_persist(config, plugins_root, database, project, user_skills)
    item = next(
        (
            entry
            for entry in inventory.capabilities
            if entry.manifest.capability_id == capability_id
        ),
        None,
    )
    if item is None:
        typer.echo(f"unknown capability ID: {capability_id}", err=True)
        raise typer.Exit(2)
    payload = _public_capability(item)
    payload["provenance"] = {
        "adapter_id": item.provenance.adapter_id,
        "locator": item.provenance.locator,
    }
    payload["verification"] = {
        "verified": item.verification.verified,
        "details": list(item.verification.details),
    }
    _emit(payload, json_output)


@capabilities_app.command("doctor")
def doctor_capabilities(
    config: ConfigOption,
    plugins_root: PluginsOption,
    database: DatabaseOption = None,
    json_output: JsonOption = False,
    project: ProjectOption = None,
    user_skills: UserSkillsOption = None,
) -> None:
    """Report malformed metadata, dependencies, and risky permissions."""
    inventory = _scan_and_persist(config, plugins_root, database, project, user_skills)
    findings = [
        {
            "capability_id": item.manifest.capability_id,
            "status": "unverified",
            "details": list(item.verification.details),
        }
        for item in inventory.capabilities
        if not item.verification.verified
    ]
    payload = {
        "diagnostics": [_public_diagnostic(item) for item in inventory.diagnostics],
        "findings": findings,
        "healthy": not findings and not inventory.diagnostics,
    }
    _emit(payload, json_output)
    if not payload["healthy"]:
        raise typer.Exit(1)


def _scan_and_persist(
    config: Path,
    plugins_root: Path,
    database: Path | None,
    project: Path | None,
    user_skills: Path | None,
) -> InventoryResult:
    project_root = (project or Path.cwd()).resolve()
    user_root = (user_skills or Path.home() / ".agents" / "skills").resolve()
    inventory = InventoryService().scan(
        [
            AgentSkillAdapter(
                roots=(
                    SkillRoot(project_root / ".agents" / "skills", CapabilityScope.PROJECT),
                    SkillRoot(project_root / ".codex" / "skills", CapabilityScope.PROJECT),
                    SkillRoot(user_root, CapabilityScope.USER),
                )
            ),
            CliToolAdapter(specs=_default_cli_specs()),
            CodexMcpAdapter(config=config),
            CodexPluginAdapter(roots=(plugins_root,)),
            CodexHookAdapter(roots=(plugins_root,), project_root=project_root),
        ]
    )
    database_path = (database or default_database_path()).resolve()
    command.upgrade(migration_config(database_path), "head")
    factory = sessionmaker(
        create_sqlite_engine(database_path), class_=Session, expire_on_commit=False
    )
    capabilities = [_public_capability(item) for item in inventory.capabilities]
    diagnostics = [_public_diagnostic(item) for item in inventory.diagnostics]
    snapshot = cast(
        Mapping[str, JsonValue],
        {"capabilities": capabilities, "diagnostics": diagnostics},
    )
    InventoryCacheRepository(factory).put(
        source_digest=inventory.inventory_digest,
        scope=tuple(sorted({item.manifest.scope.value for item in inventory.capabilities})),
        snapshot=snapshot,
    )
    verification_repository = CapabilityVerificationRepository(factory)
    for item in inventory.capabilities:
        verification_repository.record(
            capability_id=item.manifest.capability_id,
            content_digest=item.manifest.content_digest,
            scope=(item.manifest.scope.value,),
            status="verified" if item.verification.verified else "unverified",
            reason="adapter verification completed",
            details=cast(
                Mapping[str, JsonValue],
                {
                    "adapter": item.provenance.adapter_id,
                    "evidence": list(item.verification.details),
                },
            ),
        )
    return inventory


def _public_capability(item: AdapterScanResult) -> dict[str, Any]:
    manifest = item.manifest
    return {
        "capability_id": manifest.capability_id,
        "compatibility": _compatibility(item),
        "kind": manifest.kind.value,
        "name": manifest.name,
        "permissions": sorted(permission.value for permission in manifest.permissions),
        "provides": sorted(manifest.provides),
        "scope": manifest.scope.value,
        "source": manifest.source,
        "status": "verified" if item.verification.verified else "unverified",
        "version": manifest.version,
    }


def _compatibility(item: AdapterScanResult) -> str:
    explicit = [
        detail.removeprefix("compatibility:")
        for detail in item.verification.details
        if detail.startswith("compatibility:")
    ]
    if explicit:
        return explicit[0]
    states = [
        detail
        for detail in item.verification.details
        if detail in {"configured", "connected", "disconnected", "connection_unknown"}
    ]
    return "; ".join(states) if states else "compatible"


def _public_diagnostic(item: InventoryDiagnostic) -> dict[str, Any]:
    return {
        "adapter_id": item.adapter_id,
        "capability_id": item.capability_id,
        "code": item.code,
        "locator": item.locator,
        "message": item.message,
    }


def _emit(payload: Mapping[str, Any], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _default_cli_specs() -> tuple[CliToolSpec, ...]:
    return (
        CliToolSpec("git", "git", ("--version",), ("version-control",)),
        CliToolSpec("pytest", "pytest", ("--version",), ("run-python-tests",)),
        CliToolSpec("python", "python", ("--version",), ("python-runtime",)),
        CliToolSpec("rg", "rg", ("--version",), ("search-code",)),
    )
