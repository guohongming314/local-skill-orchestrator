"""Interactively resolve actionable Doctor drift without guessing user intent."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from vibe.commands.diff import _load_blueprint
from vibe.commands.doctor import _project_report
from vibe.commands.init import _project_changeset
from vibe.doctor.drift import DriftClassification
from vibe.doctor.report import DoctorFinding, Severity
from vibe.materialize.changeset import (
    ChangeKind,
    ChangeOperation,
    ChangeProposal,
    ChangeSet,
    build_changeset,
    render_dry_run,
)
from vibe.materialize.ownership import FileOwnership
from vibe.materialize.writer import apply_changeset

_DECISIONS_PATH = ".ai-project/decisions.md"
_MARKER_PREFIX = "<!-- vibe-reconcile "


@dataclass(frozen=True)
class ResolutionPreview:
    finding: DoctorFinding
    accept_reality: ChangeSet
    restore_intent: ChangeSet
    operation: ChangeOperation | None


def reconcile_command(
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    include_security: Annotated[bool, typer.Option("--include-security")] = False,
) -> None:
    """Preview and explicitly resolve actionable project drift."""
    root = (path or Path.cwd()).resolve()
    report = _project_report(root)
    generated = _project_changeset(root, _load_blueprint(root))
    previews = tuple(
        _preview(root, finding, generated)
        for finding in report.findings
        if _is_offered(finding, include_security=include_security)
    )

    offered = {item.finding for item in previews}
    for finding in report.findings:
        typer.echo(f"[{_classification(finding).value}] {finding.code}: {finding.summary}")
        if finding not in offered:
            typer.echo("  listed only; no reconciliation choice is offered")

    if not previews:
        typer.echo("No actionable findings to reconcile.")
        return

    for preview in previews:
        typer.echo(f"\nFinding: {preview.finding.code}")
        typer.echo("Accept reality preview:")
        typer.echo(render_dry_run(preview.accept_reality))
        typer.echo("Restore intent preview:")
        typer.echo(render_dry_run(preview.restore_intent))

    if dry_run:
        return

    choices: list[tuple[ResolutionPreview, str]] = []
    for preview in previews:
        choice = typer.prompt(
            f"Resolve {preview.finding.code} (accept/restore/skip)",
            default="skip",
        ).strip().lower()
        if choice not in {"accept", "restore", "skip"}:
            typer.echo(f"Invalid resolution: {choice}", err=True)
            raise typer.Exit(2)
        if choice != "skip":
            choices.append((preview, choice))

    if not choices:
        typer.echo("No resolutions selected.")
        return

    changeset = _combined_changeset(root, choices)
    apply_changeset(changeset)
    typer.echo(render_dry_run(changeset))
    typer.echo("Selected resolutions applied atomically.")


def _preview(root: Path, finding: DoctorFinding, generated: ChangeSet) -> ResolutionPreview:
    operation = _matching_operation(finding, generated)
    return ResolutionPreview(
        finding=finding,
        accept_reality=_resolution_changeset(root, finding, "accept-reality", None),
        restore_intent=_resolution_changeset(root, finding, "restore-intent", operation),
        operation=operation,
    )


def _combined_changeset(
    root: Path, choices: list[tuple[ResolutionPreview, str]]
) -> ChangeSet:
    proposals: dict[str, ChangeProposal] = {}
    entries: list[dict[str, str]] = []
    for preview, choice in choices:
        operation = preview.operation if choice == "restore" else None
        if operation is not None and operation.kind is not ChangeKind.UNCHANGED:
            proposals[operation.path] = _proposal_from_operation(operation)
        resolution = "accept-reality" if choice == "accept" else "restore-intent"
        entries.append(_decision_entry(root, preview.finding, resolution))
    proposals[_DECISIONS_PATH] = _decisions_proposal(root, entries)
    return build_changeset(root, tuple(proposals.values()))


def _resolution_changeset(
    root: Path,
    finding: DoctorFinding,
    resolution: str,
    operation: ChangeOperation | None,
) -> ChangeSet:
    proposals: list[ChangeProposal] = []
    if operation is not None and operation.kind is not ChangeKind.UNCHANGED:
        proposals.append(_proposal_from_operation(operation))
    proposals.append(_decisions_proposal(root, [_decision_entry(root, finding, resolution)]))
    return build_changeset(root, tuple(proposals))


def _proposal_from_operation(operation: ChangeOperation) -> ChangeProposal:
    return ChangeProposal(
        path=operation.path,
        desired_content=operation.after_content,
        ownership=operation.ownership,
        source="reconcile:restore-intent",
        reason=f"Restore generated intent for {operation.path}.",
        sensitivity=operation.sensitivity,
    )


def _decisions_proposal(root: Path, entries: list[dict[str, str]]) -> ChangeProposal:
    target = root / _DECISIONS_PATH
    current = (
        target.read_text(encoding="utf-8-sig")
        if target.is_file()
        else "# Project decisions\n"
    )
    lines = [current.rstrip(), "", "## Reconcile decisions", ""]
    lines.extend(
        _MARKER_PREFIX + json.dumps(entry, sort_keys=True, separators=(",", ":")) + " -->"
        for entry in entries
    )
    return ChangeProposal(
        path=_DECISIONS_PATH,
        desired_content="\n".join(lines) + "\n",
        ownership=FileOwnership.OWNED,
        source="reconcile:decision",
        reason="Record the explicit drift resolution.",
    )


def _decision_entry(root: Path, finding: DoctorFinding, resolution: str) -> dict[str, str]:
    path = _finding_path(finding)
    entry = {"code": finding.code, "resolution": resolution}
    if path is not None:
        entry["path"] = path
        target = root / path
        if target.is_file():
            entry["digest"] = hashlib.sha256(target.read_bytes()).hexdigest()
    return entry


def _matching_operation(
    finding: DoctorFinding, changeset: ChangeSet
) -> ChangeOperation | None:
    path = _finding_path(finding)
    if path is None:
        return None
    return next((item for item in changeset.operations if item.path == path), None)


def _finding_path(finding: DoctorFinding) -> str | None:
    return next(
        (
            item
            for item in finding.evidence
            if item.startswith((".ai-project/", ".agents/", "AGENTS.md"))
        ),
        None,
    )


def _classification(finding: DoctorFinding) -> DriftClassification:
    if finding.classification is not None:
        return finding.classification
    if finding.code.startswith("drift."):
        return (
            DriftClassification.ACTIONABLE
            if finding.severity in {Severity.ACTIONABLE, Severity.ERROR}
            else DriftClassification.EXPECTED
        )
    return DriftClassification.BLOCKING


def _is_offered(finding: DoctorFinding, *, include_security: bool) -> bool:
    classification = _classification(finding)
    return classification is DriftClassification.ACTIONABLE or (
        include_security and classification is DriftClassification.SECURITY
    )
