"""Reusable configuration and local-capability health checks."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import ValidationError

from vibe.doctor.drift import DriftClassification
from vibe.doctor.report import DoctorFinding, DoctorReport, Severity, aggregate_findings
from vibe.inventory.service import InventoryResult
from vibe.materialize.project_hooks import command_project_paths
from vibe.materialize.templates import (
    CapabilityLock,
    CapabilityUsage,
    ProjectPolicy,
    ProjectTaskPolicies,
    ProjectWorkflows,
    RenderedCapabilities,
)
from vibe.migrations.registry import (
    MissingMigrationError,
    UnknownSchemaVersionError,
    default_registry,
    discover_artifacts,
)
from vibe.models.base import VersionedModel
from vibe.models.blueprint import Blueprint
from vibe.persistence.database import default_database_path
from vibe.policy.org import load_org_policy
from vibe.practices.calibration import CalibrationOutcome, pending_suggestions
from vibe.practices.loader import load_practice_pack

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


class SchemaVersionCheck:
    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        findings: list[DoctorFinding] = []
        for artifact in discover_artifacts(context.root):
            latest = default_registry.latest_version(artifact.kind)
            if latest is None:
                continue
            current = artifact.payload.get("schema_version")
            try:
                result = default_registry.migrate(artifact.kind, artifact.payload)
            except (UnknownSchemaVersionError, MissingMigrationError, ValueError) as error:
                findings.append(
                    DoctorFinding(
                        code="configuration.schema-unsupported",
                        severity=Severity.ERROR,
                        summary="Artifact schema version cannot be migrated by this release.",
                        evidence=(artifact.relative_path, str(error)),
                        remediation=(
                            "Upgrade vibe or restore an artifact with a supported schema version."
                        ),
                    )
                )
                continue
            if result.provenance:
                findings.append(
                    DoctorFinding(
                        code="configuration.schema-outdated",
                        severity=Severity.WARNING,
                        summary="Artifact uses an older supported schema version.",
                        evidence=(artifact.relative_path, f"{current} -> {latest}"),
                        remediation="Review `vibe migrate --dry-run`, then run `vibe migrate`.",
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
            if provider.provider_id not in available and provider.provider_id != "hook.project"
        )


class InstalledCapabilityDriftCheck:
    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        lock = _load(context.root, ".ai-project/capabilities.lock", CapabilityLock)
        if lock is None:
            return ()
        available = {
            item.manifest.capability_id: item.manifest for item in context.inventory.capabilities
        }
        findings: list[DoctorFinding] = []
        for provider in lock.providers:
            manifest = available.get(provider.provider_id)
            if manifest is None or provider.content_digest in {
                manifest.content_digest,
                _installed_digest(context.root, manifest.source),
            }:
                continue
            findings.append(
                DoctorFinding(
                    code="capability.digest-drift",
                    severity=Severity.ERROR,
                    summary="An installed capability artifact no longer matches its locked digest.",
                    evidence=(
                        provider.provider_id,
                        provider.content_digest,
                        manifest.content_digest,
                    ),
                    remediation=(
                        "Stop using the capability, inspect the artifact, and reinstall only "
                        "from the approved pinned source."
                    ),
                    classification=DriftClassification.SECURITY,
                )
            )
        return tuple(findings)


def _installed_digest(root: Path, source: str) -> str | None:
    target = Path(source)
    if not target.is_absolute():
        target = root / target
    if target.is_file():
        return f"sha256:{hashlib.sha256(target.read_bytes()).hexdigest()}"
    return None


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
                            "Reject the expansion or explicitly re-approve it before updating "
                            "project policy."
                        ),
                        classification=DriftClassification.BLOCKING,
                    )
                )
        return tuple(findings)


class ProjectHookGovernanceCheck:
    """Verify project-local Hooks still match their explicit approval record."""

    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        path = context.root / ".codex" / "hooks.json"
        lock = _load(context.root, ".ai-project/capabilities.lock", CapabilityLock)
        if lock is None:
            return (
                (
                    self._finding(
                        "hook.project-untrusted",
                        "Project-local Hooks have no approval lock record.",
                    ),
                )
                if path.is_file()
                else ()
            )
        provider = next(
            (item for item in lock.providers if item.provider_id == "hook.project"), None
        )
        if provider is None:
            return (
                (
                    self._finding(
                        "hook.project-untrusted",
                        "Project-local Hooks have no approval lock record.",
                    ),
                )
                if path.is_file()
                else ()
            )
        findings: list[DoctorFinding] = []
        path = context.root / provider.source
        if not path.is_file():
            findings.append(self._finding("hook.file-missing", "Approved Hook file is missing."))
            return tuple(findings)
        try:
            raw = path.read_bytes()
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError, UnicodeError):
            return (self._finding("hook.digest-drift", "Approved Hook definition was changed."),)
        if hashlib.sha256(raw).hexdigest() != provider.content_digest:
            findings.append(
                self._finding("hook.digest-drift", "Approved Hook definition was changed.")
            )
        if not provider.hook_approved:
            findings.append(
                self._finding(
                    "hook.project-untrusted",
                    "Project-local Hooks are not trusted for this project.",
                )
            )
        if not provider.hook_approval_provenance:
            findings.append(
                self._finding(
                    "hook.approval-missing",
                    "Project Hook approval provenance is absent.",
                )
            )
        if not provider.hook_trust_digest:
            findings.append(
                self._finding("hook.trust-missing", "Project Hook trust provenance is absent.")
            )
        elif provider.hook_trust_digest != provider.content_digest or (
            hashlib.sha256(raw).hexdigest() != provider.hook_trust_digest
        ):
            findings.append(
                self._finding(
                    "hook.trust-drift",
                    "Project Hook trust is not bound to the current definition.",
                )
            )
        actual_permissions = _hook_permissions(payload)
        approved_permissions = set(provider.hook_permissions or ())
        widened = sorted(actual_permissions - approved_permissions)
        if widened:
            findings.append(
                self._finding(
                    "hook.permission-widened",
                    "Project Hook permissions exceed the approved set.",
                    *widened,
                )
            )
        if provider.hook_command:
            script, contained = _project_script_path(context.root, provider.hook_command)
            if not contained:
                findings.append(
                    self._finding(
                        "hook.command-invalid",
                        "Approved Hook command escapes the project root.",
                    )
                )
            elif script is not None and not script.is_file():
                findings.append(
                    self._finding(
                        "hook.command-missing",
                        "Approved Hook command script is missing.",
                        str(script.relative_to(context.root)),
                    )
                )
        return tuple(findings)

    @staticmethod
    def _finding(code: str, summary: str, *evidence: str) -> DoctorFinding:
        return DoctorFinding(
            code=code,
            severity=Severity.ERROR,
            summary=summary,
            evidence=evidence or (".codex/hooks.json",),
            remediation="Restore the approved definition or renew project Hook trust.",
            classification=DriftClassification.SECURITY,
        )


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


_UNUSED_OUTCOME_THRESHOLD = 3
_OVERRIDE_THRESHOLD = 3
_VERIFICATION_FAILURE_THRESHOLD = 3


@dataclass(frozen=True)
class _RecordedOutcome:
    task_id: str
    capabilities_used: tuple[str, ...]
    verification_passed: bool
    unused_recommendations: tuple[str, ...]


class OutcomeInsightsCheck:
    """Turn repeated low-sensitivity task outcomes into review-only suggestions."""

    def __init__(self, database: Path | None = None) -> None:
        self._database = (database or default_database_path()).resolve()

    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        outcomes = self._read_outcomes()
        if not outcomes:
            return ()

        findings: list[DoctorFinding] = []
        lock = _load(context.root, ".ai-project/capabilities.lock", CapabilityLock)
        if len(outcomes) >= _UNUSED_OUTCOME_THRESHOLD and lock is not None:
            used = {capability for record in outcomes for capability in record.capabilities_used}
            evidence_tasks = tuple(record.task_id for record in outcomes)
            findings.extend(
                DoctorFinding(
                    code="outcome.capability-unused",
                    severity=Severity.ACTIONABLE,
                    summary="An installed capability has not been used in recent outcomes.",
                    evidence=(provider.provider_id, *evidence_tasks),
                    remediation=(
                        "Review whether the capability is still needed; remove it only after "
                        "confirming the project policy no longer requires it."
                    ),
                )
                for provider in lock.providers
                if provider.provider_id not in used
            )

        overridden: dict[str, list[str]] = {}
        failed: dict[str, list[str]] = {}
        for record in outcomes:
            for capability in record.unused_recommendations:
                overridden.setdefault(capability, []).append(record.task_id)
            if not record.verification_passed:
                for capability in record.capabilities_used:
                    failed.setdefault(capability, []).append(record.task_id)

        findings.extend(
            DoctorFinding(
                code="outcome.recommendation-overridden",
                severity=Severity.ACTIONABLE,
                summary="The same capability recommendation is repeatedly not used.",
                evidence=(capability, *task_ids),
                remediation=(
                    "Review the repeated overrides and consider encoding the preference as "
                    "project policy; do not change policy automatically."
                ),
            )
            for capability, task_ids in overridden.items()
            if len(task_ids) >= _OVERRIDE_THRESHOLD
        )
        findings.extend(
            DoctorFinding(
                code="outcome.verification-failing",
                severity=Severity.ACTIONABLE,
                summary="A capability repeatedly appears in outcomes that fail verification.",
                evidence=(capability, *task_ids),
                remediation=(
                    "Review the verification failures and select a fallback provider or "
                    "document a deliberate downgrade."
                ),
            )
            for capability, task_ids in failed.items()
            if len(task_ids) >= _VERIFICATION_FAILURE_THRESHOLD
        )
        return tuple(findings)

    def _read_outcomes(self) -> tuple[_RecordedOutcome, ...]:
        if not self._database.is_file():
            return ()
        try:
            with sqlite3.connect(self._database) as connection:
                rows = connection.execute(
                    """SELECT task_id, capabilities_used_json, verification_passed,
                              unused_recommendations_json
                       FROM task_outcomes
                       ORDER BY created_at, task_id"""
                ).fetchall()
        except sqlite3.Error:
            return ()
        return tuple(
            _RecordedOutcome(
                task_id=str(task_id),
                capabilities_used=tuple(json.loads(used_json)["items"]),
                verification_passed=bool(verification_passed),
                unused_recommendations=tuple(json.loads(unused_json)["items"]),
            )
            for task_id, used_json, verification_passed, unused_json in rows
        )


class CalibrationSuggestionsCheck:
    """Surface pending outcome-calibration changes for explicit user review."""

    def __init__(self, database: Path | None = None) -> None:
        self._database = (database or default_database_path()).resolve()

    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        outcomes = OutcomeInsightsCheck(self._database)._read_outcomes()
        suggestions = pending_suggestions(
            context.root,
            tuple(
                CalibrationOutcome(
                    task_id=record.task_id,
                    unused_recommendations=record.unused_recommendations,
                )
                for record in outcomes
            ),
        )
        return tuple(
            DoctorFinding(
                code="outcome.calibration-pending",
                severity=Severity.ACTIONABLE,
                summary=(
                    f"Recommendation strength for {suggestion.capability} can be "
                    f"changed from {suggestion.current_strength.value} to "
                    f"{suggestion.proposed_strength.value}."
                ),
                evidence=(
                    suggestion.capability,
                    suggestion.rule,
                    *suggestion.evidence,
                ),
                remediation=(
                    "Review the listed outcomes and explicitly confirm or reject this "
                    "project calibration; it will not be applied automatically."
                ),
            )
            for suggestion in suggestions
        )


class OrganizationPolicyCheck:
    """Report generated project configuration that violates current org guardrails."""

    def check(self, context: DoctorContext) -> tuple[DoctorFinding, ...]:
        try:
            policy, path = load_org_policy(context.root)
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError):
            return (
                DoctorFinding(
                    code="organization.policy-invalid",
                    severity=Severity.ERROR,
                    summary="The organization policy cannot be loaded.",
                    evidence=(str(context.root / "org-policy.yaml"),),
                    remediation="Repair the organization policy before changing project config.",
                    classification=DriftClassification.BLOCKING,
                ),
            )
        if policy is None:
            return ()
        lock = _load(context.root, ".ai-project/capabilities.lock", CapabilityLock)
        capabilities = _load(context.root, ".ai-project/capabilities.yaml", RenderedCapabilities)
        if lock is None or capabilities is None:
            return ()
        violations: list[str] = []
        for provider in lock.providers:
            if provider.provider_id in policy.blocked_capability_ids or (
                policy.approved_capability_ids
                and provider.provider_id not in policy.approved_capability_ids
            ):
                violations.append(provider.provider_id)
            if provider.publisher in policy.blocked_publishers or (
                provider.publisher is not None
                and policy.approved_publishers
                and provider.publisher not in policy.approved_publishers
            ):
                violations.append(provider.publisher)
        project_policy = _load(context.root, ".ai-project/policy.yaml", ProjectPolicy)
        if project_policy is not None:
            violations.extend(
                permission
                for permission in project_policy.permissions
                if permission not in {item.value for item in policy.allowed_permissions}
            )
        resolved_requirements = {str(item.get("requirement")) for item in capabilities.resolutions}
        packs_root = Path(__file__).resolve().parents[3] / "practice-packs"
        for pack_id in sorted(policy.mandatory_practice_packs):
            pack_path = packs_root / pack_id / "pack.yaml"
            try:
                pack = load_practice_pack(pack_path)
            except (OSError, UnicodeError, yaml.YAMLError, ValidationError, ValueError):
                violations.append(pack_id)
                continue
            required = {item.capability for item in pack.requirements}
            if not required.issubset(resolved_requirements):
                violations.append(pack_id)
        if not violations:
            return ()
        return (
            DoctorFinding(
                code="organization.policy-violation",
                severity=Severity.ERROR,
                summary="Project configuration violates the current organization policy.",
                evidence=tuple(dict.fromkeys((str(path), *violations))),
                remediation="Regenerate project configuration under the current org policy.",
                classification=DriftClassification.BLOCKING,
            ),
        )


DEFAULT_CHECKS: tuple[DoctorCheck, ...] = (
    SchemaVersionCheck(),
    ConfigurationSchemaCheck(),
    LockedProviderCheck(),
    InstalledCapabilityDriftCheck(),
    CommandAvailabilityCheck(),
    PermissionDeltaCheck(),
    ProjectHookGovernanceCheck(),
    OrganizationPolicyCheck(),
    ConversationRecoveryCheck(),
    OutcomeInsightsCheck(),
    CalibrationSuggestionsCheck(),
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


def _hook_permissions(payload: Any) -> set[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("hooks"), dict):
        return set()
    permissions: set[str] = set()
    for entries in payload["hooks"].values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("permissions"), list):
                continue
            permissions.update(str(item) for item in entry["permissions"])
    return permissions


def _project_script_path(root: Path, command: str) -> tuple[Path | None, bool]:
    try:
        paths = command_project_paths(command)
    except ValueError:
        return None, False
    scripts = tuple(path for path in paths if str(path).endswith((".py", ".sh", ".js", ".ts")))
    if not scripts:
        return None, True
    candidate = root / str(scripts[0])
    resolved = candidate.resolve()
    return resolved, resolved.is_relative_to(root.resolve())
