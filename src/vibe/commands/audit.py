"""Query the persisted governance trail and report integrity gaps."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
from alembic import command
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, sessionmaker

from vibe.persistence.database import create_sqlite_engine, default_database_path, migration_config
from vibe.persistence.repositories import AuditEventRecord, AuditEventRepository, JsonValue


class AuditEventView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: int
    run_id: str | None
    event_kind: str
    summary: str
    details: dict[str, JsonValue]
    redacted: bool
    created_at: datetime


class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal["install-without-approval"]
    event_id: int
    capability_id: str
    severity: Literal["gap"] = "gap"
    summary: str


class AuditFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str | None
    event_kind: str | None
    from_time: datetime | None
    to_time: datetime | None


class AuditReport(BaseModel):
    """Published JSON schema for ``vibe audit --json``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    filters: AuditFilters
    events: tuple[AuditEventView, ...]
    findings: tuple[AuditFinding, ...]


def audit_command(
    database: Annotated[Path | None, typer.Option("--database")] = None,
    capability: Annotated[str | None, typer.Option("--capability")] = None,
    event_kind: Annotated[str | None, typer.Option("--event-kind")] = None,
    from_time: Annotated[datetime | None, typer.Option("--from")] = None,
    to_time: Annotated[datetime | None, typer.Option("--to")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show filtered audit events and governance-integrity findings."""
    if from_time is not None and to_time is not None and from_time > to_time:
        typer.echo("--from must not be later than --to", err=True)
        raise typer.Exit(2)

    database_path = (database or default_database_path()).resolve()
    command.upgrade(migration_config(database_path), "head")
    factory = sessionmaker(
        create_sqlite_engine(database_path), class_=Session, expire_on_commit=False
    )
    repository = AuditEventRepository(factory)
    events = repository.query(
        from_time=from_time,
        to_time=to_time,
        event_kind=event_kind,
        capability_id=capability,
    )
    integrity_events = repository.query(capability_id=capability)
    displayed_ids = {event.event_id for event in events}
    report = AuditReport(
        filters=AuditFilters(
            capability=capability,
            event_kind=event_kind,
            from_time=from_time,
            to_time=to_time,
        ),
        events=tuple(_event_view(event) for event in events),
        findings=tuple(
            finding
            for finding in _integrity_findings(integrity_events)
            if finding.event_id in displayed_ids
        ),
    )
    if json_output:
        typer.echo(
            json.dumps(
                report.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return
    _emit_human(report)


def _event_view(event: AuditEventRecord) -> AuditEventView:
    return AuditEventView(
        event_id=event.event_id,
        run_id=event.run_id,
        event_kind=event.event_type,
        summary=event.summary,
        details=event.details,
        redacted=event.redacted,
        created_at=event.created_at,
    )


def _integrity_findings(events: tuple[AuditEventRecord, ...]) -> tuple[AuditFinding, ...]:
    approvals: set[str] = set()
    findings: list[AuditFinding] = []
    for event in events:
        capability_id = _capability_id(event)
        if capability_id is None:
            continue
        if _is_approval(event):
            approvals.add(capability_id)
        elif event.event_type == "capability.install" and capability_id not in approvals:
            findings.append(
                AuditFinding(
                    code="install-without-approval",
                    event_id=event.event_id,
                    capability_id=capability_id,
                    summary="Install event has no earlier matching approval event.",
                )
            )
    return tuple(findings)


def _capability_id(event: AuditEventRecord) -> str | None:
    for key in ("capability_id", "capability", "provider_id"):
        value = event.details.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_approval(event: AuditEventRecord) -> bool:
    if "approval" not in event.event_type:
        return False
    decision = event.details.get("decision")
    approved = event.details.get("approved")
    return decision not in {"denied", "rejected", "declined"} and approved is not False


def _emit_human(report: AuditReport) -> None:
    typer.echo("CREATED_AT | EVENT_KIND | CAPABILITY | SUMMARY")
    for event in report.events:
        capability = _view_capability_id(event) or "-"
        typer.echo(
            f"{event.created_at.isoformat()} | {event.event_kind} | {capability} | {event.summary}"
        )
    typer.echo("")
    if not report.findings:
        typer.echo("No integrity gaps found.")
        return
    typer.echo("Integrity findings:")
    for finding in report.findings:
        typer.echo(
            f"[gap] {finding.code} event={finding.event_id} "
            f"capability={finding.capability_id}: {finding.summary}"
        )


def _view_capability_id(event: AuditEventView) -> str | None:
    for key in ("capability_id", "capability", "provider_id"):
        value = event.details.get(key)
        if isinstance(value, str) and value:
            return value
    return None
