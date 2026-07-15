"""Expose project configuration health as human-readable or stable JSON output."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError

from vibe.commands.capabilities import _default_cli_specs
from vibe.commands.init import _project_changeset
from vibe.commands.project_plan import build_project_plan, scan_project_inventory
from vibe.compiler.invalidation import InvalidationReason
from vibe.doctor.checks import run_health_checks
from vibe.doctor.drift import detect_drift
from vibe.doctor.report import (
    DoctorFinding,
    DoctorReport,
    Severity,
    aggregate_findings,
)
from vibe.inspect.repository import inspect_repository
from vibe.inspect.stack import inspect_stack
from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.adapters.base import CapabilityAdapter
from vibe.inventory.adapters.cli_tool import CliToolAdapter
from vibe.inventory.service import InventoryResult, InventoryService
from vibe.models.blueprint import Blueprint
from vibe.models.capability import CapabilityScope
from vibe.models.repository import RepositorySnapshot


def doctor_command(
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Report project configuration health and drift without modifying files."""
    root = (path or Path.cwd()).resolve()
    report = _project_report(root)
    status = _report_status(report)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "schema_version": "1",
                    "status": status,
                    "findings": [_finding_payload(item) for item in report.findings],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        typer.echo(f"Project health: {status}")
        for finding in report.findings:
            typer.echo(
                f"[{finding.severity.value}] {finding.code}: {finding.summary}"
            )
            typer.echo(f"  evidence: {', '.join(finding.evidence)}")
            typer.echo(f"  remediation: {finding.remediation}")
    code = exit_code_for_report(report)
    if code:
        raise typer.Exit(code)


def exit_code_for_report(report: DoctorReport) -> int:
    if any(item.severity is Severity.ERROR for item in report.findings):
        return 2
    if any(item.severity is Severity.WARNING for item in report.findings):
        return 1
    return 0


def _project_report(root: Path) -> DoctorReport:
    inventory = _current_inventory(root)
    health = run_health_checks(root, inventory)
    blueprint = _load_blueprint(root)
    if blueprint is None:
        return health
    current = _complete_snapshot(root)
    baseline = current.model_copy(
        update={"source_digest": blueprint.repository_digest}
    )
    project_inventory = scan_project_inventory(root)
    project_plan = build_project_plan(
        root, blueprint, current, inventory=project_inventory
    )
    changeset = _project_changeset(
        root,
        blueprint,
        inventory=project_plan.inventory,
        resolution=project_plan.resolution,
        requirements=project_plan.requirements,
    )
    drift = detect_drift(baseline, current, changeset)
    drift_findings = tuple(
        finding
        for reason in drift.reasons
        if (finding := _drift_finding(reason)) is not None
        and not _accepted_reality(root, finding)
    )
    return aggregate_findings((*health.findings, *drift_findings))


def _current_inventory(root: Path) -> InventoryResult:
    skill_root = root / ".agents" / "skills"
    adapters: tuple[CapabilityAdapter, ...] = (
        CliToolAdapter(specs=_default_cli_specs()),
        AgentSkillAdapter(
            roots=(SkillRoot(skill_root, CapabilityScope.PROJECT),)
        ),
    )
    return InventoryService().scan(adapters)


def _complete_snapshot(root: Path) -> RepositorySnapshot:
    snapshot = inspect_repository(root)
    facts = (*snapshot.facts, *inspect_stack(snapshot.root))
    return snapshot.model_copy(
        update={"facts": tuple(sorted(facts, key=lambda item: item.key))}
    )


def _load_blueprint(root: Path) -> Blueprint | None:
    target = root / ".ai-project" / "blueprint.yaml"
    if not target.is_file():
        return None
    try:
        return Blueprint.model_validate(
            yaml.safe_load(target.read_text(encoding="utf-8-sig"))
        )
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError):
        return None


def _accepted_reality(root: Path, finding: DoctorFinding) -> bool:
    decisions = root / ".ai-project" / "decisions.md"
    if not decisions.is_file():
        return False
    if finding.evidence == (".ai-project/decisions.md",):
        return True
    try:
        lines = decisions.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return False
    prefix = "<!-- vibe-reconcile "
    for line in lines:
        if not line.startswith(prefix) or not line.endswith(" -->"):
            continue
        try:
            entry = json.loads(line[len(prefix) : -4])
        except (json.JSONDecodeError, TypeError):
            continue
        path = entry.get("path")
        target = root / path if isinstance(path, str) else None
        if (
            entry.get("resolution") == "accept-reality"
            and entry.get("code") == finding.code
            and path in finding.evidence
            and target is not None
            and target.is_file()
            and entry.get("digest") == hashlib.sha256(target.read_bytes()).hexdigest()
        ):
            return True
    return False


def _drift_finding(reason: InvalidationReason) -> DoctorFinding:
    invalidating = reason.invalidates_configuration
    return DoctorFinding(
        code=f"drift.{reason.kind.value}",
        severity=Severity.ERROR if invalidating else Severity.INFO,
        summary=(
            "Generated project configuration is stale."
            if invalidating
            else "Repository facts changed without invalidating configuration."
        ),
        evidence=reason.sources,
        remediation=(
            "Review `vibe diff`, then run `vibe init --dry-run` before applying changes."
            if invalidating
            else "No action is required unless the project intent also changed."
        ),
    )


def _finding_payload(finding: DoctorFinding) -> dict[str, object]:
    return {
        "code": finding.code,
        "severity": finding.severity.value,
        "summary": finding.summary,
        "evidence": list(finding.evidence),
        "remediation": finding.remediation,
        "classification": (
            finding.classification.value if finding.classification is not None else None
        ),
    }


def _report_status(report: DoctorReport) -> str:
    code = exit_code_for_report(report)
    return ("healthy", "warning", "error")[code]
