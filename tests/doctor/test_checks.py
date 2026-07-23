from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibe.doctor.checks import run_health_checks
from vibe.doctor.report import Severity
from vibe.inventory.adapters.base import (
    AdapterProvenance,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.inventory.service import InventoryResult
from vibe.materialize.project_hooks import ProjectHookPolicy
from vibe.materialize.templates import render_project_configuration
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)
from vibe.models.decisions import (
    DecisionProvenance,
    DecisionSource,
    NetworkDecision,
    NetworkPolicy,
    ProjectDecisions,
)
from vibe.models.resolution import CapabilityResolution, ResolutionPlan, ResolutionStatus
from vibe.models.risk import RiskLevel
from vibe.practices.models import RequirementStrength
from vibe.resolver.requirements import AbstractCapabilityRequirement


def inventory(
    *, permissions: frozenset[Permission] = frozenset({Permission.EXECUTE_COMMAND})
) -> InventoryResult:
    manifest = CapabilityManifest(
        capability_id="cli.pytest",
        name="pytest",
        kind=CapabilityKind.CLI_TOOL,
        scope=CapabilityScope.SYSTEM,
        source="pytest",
        provides=("testing",),
        permissions=permissions,
        version="8.4.2",
        content_digest="current-pytest-digest",
        verified=True,
    )
    return InventoryResult(
        capabilities=(
            AdapterScanResult(
                manifest=manifest,
                provenance=AdapterProvenance("fixture", "pytest"),
                verification=AdapterVerification(True),
            ),
        ),
        diagnostics=(),
        inventory_digest="current-inventory-digest",
    )


def write_configuration(
    root: Path,
    current: InventoryResult,
    *,
    hook_policy: ProjectHookPolicy | None = None,
) -> None:
    blueprint = Blueprint(
        project_name="doctor-fixture",
        goal="Check project health",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        repository_digest="repository-digest",
        decisions=ProjectDecisions(
            network_policy=NetworkDecision(
                value=NetworkPolicy.DENIED,
                provenance=DecisionProvenance(
                    source=DecisionSource.REPOSITORY_EVIDENCE,
                    reference="test-fixture",
                ),
            )
        ),
    )
    plan = ResolutionPlan(
        blueprint_digest="blueprint-digest",
        inventory_digest=current.inventory_digest,
        resolutions=(
            CapabilityResolution(
                requirement="testing",
                status=ResolutionStatus.SELECTED,
                capability_id="cli.pytest",
                reason="selected fixture provider",
            ),
        ),
    )
    for relative, content in (
        render_project_configuration(
            blueprint,
            plan,
            current,
            requirements=(
                AbstractCapabilityRequirement(
                    capability="testing",
                    strength=RequirementStrength.REQUIRED,
                    originating_packs=("doctor-fixture",),
                    originating_requirements=("testing",),
                    reasons=("Health checks require a test provider.",),
                    verification=("Run the selected test provider.",),
                ),
            ),
            hook_policy=hook_policy,
        )
        .as_dict()
        .items()
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


pytestmark = pytest.mark.validation


def test_healthy_configuration_reports_success(tmp_path: Path) -> None:
    current = inventory()
    write_configuration(tmp_path, current)

    report = run_health_checks(tmp_path, current, lambda command: f"/bin/{command}")

    assert report.healthy
    assert report.findings == ()


def test_doctor_reports_unknown_network_policy_and_unresolved_required_gap(
    tmp_path: Path,
) -> None:
    current = inventory()
    blueprint = Blueprint(
        project_name="doctor-fixture",
        goal="Check unresolved recommendations",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        repository_digest="repository-digest",
        decisions=ProjectDecisions(),
    )
    plan = ResolutionPlan(
        blueprint_digest="blueprint-digest",
        inventory_digest=current.inventory_digest,
        resolutions=(
            CapabilityResolution(
                requirement="quality.gates",
                status=ResolutionStatus.GAP,
                reason="no provider selected",
            ),
        ),
    )
    rendered = render_project_configuration(
        blueprint,
        plan,
        current,
        requirements=(
            AbstractCapabilityRequirement(
                capability="quality.gates",
                strength=RequirementStrength.REQUIRED,
                originating_packs=("base-engineering",),
                originating_requirements=("quality-gates",),
                reasons=("Quality gates are required.",),
                verification=("Run project quality gates.",),
            ),
        ),
    )
    for relative, content in rendered.as_dict().items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    findings = run_health_checks(tmp_path, current).findings

    assert any(item.code == "unknown-capability-permission" for item in findings)
    assert any(item.code == "unresolved-required-capability" for item in findings)


def test_invalid_schema_is_distinct_and_does_not_expose_values(tmp_path: Path) -> None:
    current = inventory()
    write_configuration(tmp_path, current)
    secret = "super-secret-token-value"
    (tmp_path / ".ai-project/policy.yaml").write_text(
        (
            "schema_version: '1'\nrisk_level: medium\ntarget_platforms: []\n"
            f"permissions: []\nsecret: {secret}\n"
        ),
        encoding="utf-8",
    )

    report = run_health_checks(tmp_path, current, lambda command: command)

    finding = next(item for item in report.findings if item.code == "configuration.invalid")
    assert finding.severity is Severity.ERROR
    assert ".ai-project/policy.yaml" in finding.evidence
    assert secret not in repr(report)
    assert finding.remediation


def test_missing_command_and_provider_are_actionable_distinct_findings(tmp_path: Path) -> None:
    locked = inventory()
    write_configuration(tmp_path, locked)

    empty = InventoryResult(capabilities=(), diagnostics=(), inventory_digest="empty-digest")
    report = run_health_checks(tmp_path, empty, lambda command: None)

    assert {item.code for item in report.findings} >= {
        "capability.provider-missing",
        "capability.command-missing",
    }
    assert all(item.remediation for item in report.findings)


def test_permission_expansion_reports_only_permission_names(tmp_path: Path) -> None:
    locked = inventory(permissions=frozenset({Permission.EXECUTE_COMMAND}))
    write_configuration(tmp_path, locked)
    expanded = inventory(permissions=frozenset({Permission.EXECUTE_COMMAND, Permission.NETWORK}))

    report = run_health_checks(tmp_path, expanded, lambda command: command)

    finding = next(
        item for item in report.findings if item.code == "capability.permission-expanded"
    )
    assert finding.severity is Severity.ERROR
    assert finding.evidence == ("cli.pytest", "network")


def test_report_aggregates_checks_deterministically(tmp_path: Path) -> None:
    current = inventory()
    write_configuration(tmp_path, current)
    lock_path = tmp_path / ".ai-project/capabilities.lock"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock["providers"][0]["provider_id"] = "cli.missing"
    lock["providers"][0]["source"] = "missing-command"
    lock_path.write_text(yaml.safe_dump(lock, sort_keys=True), encoding="utf-8")

    first = run_health_checks(tmp_path, current, lambda command: None)
    second = run_health_checks(tmp_path, current, lambda command: None)

    assert first == second
    assert tuple(item.code for item in first.findings) == tuple(
        sorted(item.code for item in first.findings)
    )


def test_orphaned_threads_and_stale_interview_checkpoints_are_reported(
    tmp_path: Path,
) -> None:
    from vibe.workflows.checkpoints import SqliteCheckpointStore
    from vibe.workflows.init_graph import InitializationGraph
    from vibe.workflows.state import InitStage

    path = tmp_path / ".vibe-init-checkpoints.sqlite3"
    store = SqliteCheckpointStore(path)
    stale = InitializationGraph(store)
    stale.start("stale-run", repository_digest="repo-v1")
    stale.advance("stale-run", InitStage.INVENTORY)
    stale.advance("stale-run", InitStage.INTERVIEW)

    orphan = InitializationGraph(store)
    orphan.start("orphan-run", repository_digest="repo-v1")
    orphan.advance("orphan-run", InitStage.INVENTORY)
    orphan.advance("orphan-run", InitStage.INTERVIEW)
    store.save_interview_progress(
        "orphan-run",
        thread_id="thread-orphan",
        answers={},
        provenance={},
        locked_questions=frozenset(),
    )
    orphan.cancel("orphan-run", reason="cancelled")

    report = run_health_checks(tmp_path, inventory())

    assert {finding.code for finding in report.findings} >= {
        "conversation.checkpoint-stale",
        "conversation.thread-orphaned",
    }


def test_tampered_installed_artifact_is_security_class_drift(tmp_path: Path) -> None:
    locked = inventory()
    write_configuration(tmp_path, locked)
    tampered = inventory()
    capability = tampered.capabilities[0]
    tampered_manifest = capability.manifest.model_copy(update={"content_digest": "tampered-digest"})
    current = InventoryResult(
        capabilities=(
            AdapterScanResult(
                manifest=tampered_manifest,
                provenance=capability.provenance,
                verification=capability.verification,
            ),
        ),
        diagnostics=tampered.diagnostics,
        inventory_digest=tampered.inventory_digest,
    )

    report = run_health_checks(tmp_path, current, lambda command: command)

    finding = next(item for item in report.findings if item.code == "capability.digest-drift")
    assert getattr(finding, "classification", None) == "security"
    assert finding.severity is Severity.ERROR


def test_permission_expansion_is_blocking_until_reapproved(tmp_path: Path) -> None:
    locked = inventory(permissions=frozenset({Permission.EXECUTE_COMMAND}))
    write_configuration(tmp_path, locked)
    expanded = inventory(permissions=frozenset({Permission.EXECUTE_COMMAND, Permission.NETWORK}))

    report = run_health_checks(tmp_path, expanded, lambda command: command)

    finding = next(
        item for item in report.findings if item.code == "capability.permission-expanded"
    )
    assert getattr(finding, "classification", None) == "blocking"
    assert "re-approv" in finding.remediation.lower()


def test_project_configuration_violating_org_policy_is_blocking(tmp_path: Path) -> None:
    current = inventory()
    write_configuration(tmp_path, current)
    (tmp_path / "org-policy.yaml").write_text(
        """schema_version: '1'
blocked_capability_ids: [cli.pytest]
mandatory_practice_packs: [base-engineering]
""",
        encoding="utf-8",
    )

    report = run_health_checks(tmp_path, current, lambda command: command)

    finding = next(item for item in report.findings if item.code == "organization.policy-violation")
    assert finding.severity is Severity.ERROR
    assert finding.classification is not None
    assert finding.classification.value == "blocking"
    assert "cli.pytest" in finding.evidence
    assert "base-engineering" in finding.evidence


def _write_hook_configuration(tmp_path: Path, *, policy: ProjectHookPolicy) -> None:
    current = inventory()
    write_configuration(tmp_path, current, hook_policy=policy)


def _approved_hook_policy(**updates: object) -> ProjectHookPolicy:
    values: dict[str, object] = {
        "events": ("PreToolUse", "Stop"),
        "script_path": ".ai-project/hooks/governance.py",
        "script_content": "# approved hook\n",
        "permissions": ("execute-command",),
        "approved": True,
        "approval_provenance": "review:hook-1",
    }
    values.update(updates)
    return ProjectHookPolicy.model_validate(values)


def test_doctor_accepts_healthy_approved_project_hook(tmp_path: Path) -> None:
    _write_hook_configuration(tmp_path, policy=_approved_hook_policy())

    report = run_health_checks(tmp_path, inventory(), lambda command: command)

    assert not any(item.code.startswith("hook.") for item in report.findings)


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        ("missing", "hook.file-missing"),
        ("tampered", "hook.digest-drift"),
        ("missing-script", "hook.script-missing"),
        ("tampered-script", "hook.script-drift"),
    ),
)
def test_doctor_reports_project_hook_security_drift(
    tmp_path: Path, mutation: str, code: str
) -> None:
    _write_hook_configuration(tmp_path, policy=_approved_hook_policy())
    script = tmp_path / ".ai-project" / "hooks" / "governance.py"
    if mutation == "missing":
        (tmp_path / ".codex" / "hooks.json").unlink()
    elif mutation == "tampered":
        (tmp_path / ".codex" / "hooks.json").write_text("{}\n", encoding="utf-8")
    elif mutation == "missing-script":
        script.unlink()
    else:
        script.write_text("# tampered hook\n", encoding="utf-8")

    finding = next(
        item
        for item in run_health_checks(tmp_path, inventory(), lambda command: command).findings
        if item.code == code
    )

    assert finding.severity is Severity.ERROR
    assert finding.classification is not None
    assert finding.classification.value == "security"


@pytest.mark.parametrize(
    ("field", "code"),
    (
        ("hook_approval_provenance", "hook.approval-missing"),
        ("hook_trust_digest", "hook.trust-missing"),
    ),
)
def test_doctor_reports_missing_hook_approval_or_trust(
    tmp_path: Path, field: str, code: str
) -> None:
    _write_hook_configuration(tmp_path, policy=_approved_hook_policy())
    lock_path = tmp_path / ".ai-project" / "capabilities.lock"
    payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    hook = next(item for item in payload["providers"] if item["provider_id"] == "hook.project")
    hook.pop(field)
    lock_path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")

    finding = next(
        item for item in run_health_checks(tmp_path, inventory()).findings if item.code == code
    )

    assert finding.classification is not None
    assert finding.classification.value == "security"


def test_doctor_reports_widened_hook_permissions(tmp_path: Path) -> None:
    _write_hook_configuration(tmp_path, policy=_approved_hook_policy())
    path = tmp_path / ".ai-project" / "capabilities.lock"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    hook = next(item for item in payload["providers"] if item["provider_id"] == "hook.project")
    hook["hook_permissions"] = []
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")

    codes = {item.code: item for item in run_health_checks(tmp_path, inventory()).findings}

    assert codes["hook.permission-widened"].classification is not None
    assert codes["hook.permission-widened"].classification.value == "security"


def test_doctor_reports_untrusted_project_hook_state(tmp_path: Path) -> None:
    _write_hook_configuration(tmp_path, policy=_approved_hook_policy())
    lock_path = tmp_path / ".ai-project" / "capabilities.lock"
    payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    hook = next(item for item in payload["providers"] if item["provider_id"] == "hook.project")
    hook["hook_approved"] = False
    lock_path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")

    finding = next(
        item
        for item in run_health_checks(tmp_path, inventory()).findings
        if item.code == "hook.project-untrusted"
    )

    assert finding.classification is not None
    assert finding.classification.value == "security"


@pytest.mark.parametrize("with_lock", (False, True))
def test_doctor_reports_unmanaged_project_hook_file(tmp_path: Path, with_lock: bool) -> None:
    if with_lock:
        write_configuration(tmp_path, inventory())
    hook = tmp_path / ".codex" / "hooks.json"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text('{"hooks": {}}\n', encoding="utf-8")

    finding = next(
        item
        for item in run_health_checks(tmp_path, inventory()).findings
        if item.code == "hook.project-untrusted"
    )

    assert finding.classification is not None
    assert finding.classification.value == "security"


def test_doctor_binds_hook_trust_digest_to_actual_content(tmp_path: Path) -> None:
    _write_hook_configuration(tmp_path, policy=_approved_hook_policy())
    lock_path = tmp_path / ".ai-project" / "capabilities.lock"
    payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    hook = next(item for item in payload["providers"] if item["provider_id"] == "hook.project")
    hook["hook_trust_digest"] = "different-trust-digest"
    lock_path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")

    codes = {item.code for item in run_health_checks(tmp_path, inventory()).findings}

    assert "hook.trust-drift" in codes


def test_doctor_rejects_noncanonical_hook_source(tmp_path: Path) -> None:
    _write_hook_configuration(tmp_path, policy=_approved_hook_policy())
    lock_path = tmp_path / ".ai-project" / "capabilities.lock"
    payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    hook = next(item for item in payload["providers"] if item["provider_id"] == "hook.project")
    hook["source"] = ".ai-project/hooks/governance.py"
    lock_path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")

    codes = {item.code for item in run_health_checks(tmp_path, inventory()).findings}

    assert "hook.source-invalid" in codes


def test_doctor_rejects_symlinked_script_outside_project(tmp_path: Path) -> None:
    _write_hook_configuration(tmp_path, policy=_approved_hook_policy())
    outside = tmp_path.parent / "outside-hook.py"
    outside.write_text("# outside\n", encoding="utf-8")
    script = tmp_path / ".ai-project" / "hooks" / "governance.py"
    script.unlink()
    script.symlink_to(outside)

    codes = {item.code for item in run_health_checks(tmp_path, inventory()).findings}

    assert "hook.script-invalid" in codes
