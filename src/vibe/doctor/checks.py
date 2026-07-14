"""Reusable configuration and local-capability health checks."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import ValidationError

from vibe.doctor.report import DoctorFinding, DoctorReport, Severity, aggregate_findings
from vibe.inventory.service import InventoryResult
from vibe.materialize.templates import (
    CapabilityLock,
    CapabilityUsage,
    ProjectPolicy,
    ProjectTaskPolicies,
    ProjectWorkflows,
    RenderedCapabilities,
)
from vibe.models.base import VersionedModel
from vibe.models.blueprint import Blueprint

CommandResolver = Callable[[str], str | None]

_SCHEMAS: dict[str, type[VersionedModel]] = {
    ".ai-project/blueprint.yaml": Blueprint,
    ".ai-project/capabilities.yaml": RenderedCapabilities,
    ".ai-project/capabilities.lock": CapabilityLock,
    ".ai-project/policy.yaml": ProjectPolicy,
    ".ai-project/workflows.yaml": ProjectWorkflows,
    ".ai-project/task-policies.yaml": ProjectTaskPolicies,
    ".ai-project/capability-usage.yaml": CapabilityUsage,
}


@dataclass(frozen=True)
class DoctorContext:
    root: Path
    inventory: InventoryResult
    command_resolver: CommandResolver


class DoctorCheck(Protocol):
    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]: ...


class ConfigurationSchemaCheck:
    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        findings: list[DoctorFinding] = []
        for relative, model in _SCHEMAS.items():
            target = context.root / relative
            if not target.is_file():
                findings.append(
                    DoctorFinding(
                        code="configuration.missing",
                        severity=Severity.ERROR,
                        summary="Required generated configuration is missing.",
                        evidence=(relative,),
                        remediation="Run `vibe init` after reviewing its dry-run output.",
                    )
                )
                continue
            try:
                payload = yaml.safe_load(target.read_text(encoding="utf-8-sig"))
                model.model_validate(payload)
            except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError) as error:
                findings.append(
                    DoctorFinding(
                        code="configuration.invalid",
                        severity=Severity.ERROR,
                        summary="Generated configuration does not match its versioned schema.",
                        evidence=(relative, type(error).__name__),
                        remediation="Review the file and regenerate it with `vibe init --dry-run`.",
                    )
                )
        return tuple(findings)


class LockedProviderCheck:
    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        lock = _load(context.root, ".ai-project/capabilities.lock", CapabilityLock)
        if lock is None:
            return ()
        available = {
            item.manifest.capability_id: item.manifest for item in context.inventory.capabilities
        }
        return tuple(
            DoctorFinding(
                code="capability.provider-missing",
                severity=Severity.ERROR,
                summary="A locked capability provider is not present locally.",
                evidence=(provider.provider_id,),
                remediation="Restore the pinned provider or review and regenerate the lockfile.",
            )
            for provider in lock.providers
            if provider.provider_id not in available
        )


class CommandAvailabilityCheck:
    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        lock = _load(context.root, ".ai-project/capabilities.lock", CapabilityLock)
        if lock is None:
            return ()
        findings: list[DoctorFinding] = []
        for provider in lock.providers:
            if provider.kind != "cli-tool":
                continue
            source = provider.source
            available = Path(source).is_file() or context.command_resolver(source) is not None
            if not available:
                findings.append(
                    DoctorFinding(
                        code="capability.command-missing",
                        severity=Severity.ERROR,
                        summary="A locked command-line provider is unavailable.",
                        evidence=(provider.provider_id, source),
                        remediation=(
                            "Install the command or select another verified local provider."
                        ),
                    )
                )
        return tuple(findings)


class PermissionDeltaCheck:
    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        lock = _load(context.root, ".ai-project/capabilities.lock", CapabilityLock)
        policy = _load(context.root, ".ai-project/policy.yaml", ProjectPolicy)
        if lock is None or policy is None:
            return ()
        locked_ids = {provider.provider_id for provider in lock.providers}
        allowed = set(policy.permissions)
        findings: list[DoctorFinding] = []
        for item in context.inventory.capabilities:
            manifest = item.manifest
            if manifest.capability_id not in locked_ids:
                continue
            expanded = sorted(
                permission.value
                for permission in manifest.permissions
                if permission.value not in allowed
            )
            if expanded:
                findings.append(
                    DoctorFinding(
                        code="capability.permission-expanded",
                        severity=Severity.ERROR,
                        summary="A provider now requests permissions beyond the approved policy.",
                        evidence=(manifest.capability_id, *expanded),
                        remediation=(
                            "Reject the expansion or explicitly review and update project policy."
                        ),
                    )
                )
        return tuple(findings)


class ConversationRecoveryCheck:
    """Report interview checkpoints that cannot be cleanly resumed or retired."""

    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        path = context.root / ".vibe-init-checkpoints.sqlite3"
        if not path.is_file():
            return ()
        try:
            with sqlite3.connect(path) as connection:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(vibe_init_checkpoints)")
                }
                if "codex_thread_id" not in columns:
                    return ()
                rows = connection.execute(
                    """SELECT run_id, stage, status, codex_thread_id
                       FROM vibe_init_checkpoints"""
                ).fetchall()
        except sqlite3.Error:
            return ()
        findings: list[DoctorFinding] = []
        for run_id, stage, status, thread_id in rows:
            if stage == "interview" and status == "running" and thread_id is None:
                findings.append(
                    DoctorFinding(
                        code="conversation.checkpoint-stale",
                        severity=Severity.WARNING,
                        summary="An interrupted interview checkpoint has no attached Codex thread.",
                        evidence=(str(run_id),),
                        remediation=(
                            "Resume the run to recreate the thread and replay confirmed answers."
                        ),
                    )
                )
            if thread_id is not None and status in {"completed", "cancelled", "failed"}:
                findings.append(
                    DoctorFinding(
                        code="conversation.thread-orphaned",
                        severity=Severity.WARNING,
                        summary="A terminal initialization run still references a Codex thread.",
                        evidence=(str(run_id), str(thread_id)),
                        remediation=(
                            "Remove the stale checkpoint after confirming the run is "
                            "no longer needed."
                        ),
                    )
                )
        return tuple(findings)


DEFAULT_CHECKS: tuple[DoctorCheck, ...] = (
    ConfigurationSchemaCheck(),
    LockedProviderCheck(),
    CommandAvailabilityCheck(),
    PermissionDeltaCheck(),
    ConversationRecoveryCheck(),
)


def run_health_checks(
    root: Path,
    inventory: InventoryResult,
    command_resolver: CommandResolver = shutil.which,
    *,
    checks: tuple[DoctorCheck, ...] = DEFAULT_CHECKS,
) -> DoctorReport:
    context = DoctorContext(root.resolve(), inventory, command_resolver)
    findings = tuple(finding for check in checks for finding in check.check(context))
    return aggregate_findings(findings)


def _load(root: Path, relative: str, model: type[VersionedModel]) -> Any | None:
    target = root / relative
    if not target.is_file():
        return None
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8-sig"))
        return model.model_validate(payload)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError):
        return None
