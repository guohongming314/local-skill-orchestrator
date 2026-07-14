from __future__ import annotations

from pathlib import Path

import yaml

from vibe.doctor.checks import run_health_checks
from vibe.doctor.report import Severity
from vibe.inventory.adapters.base import (
    AdapterProvenance,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.inventory.service import InventoryResult
from vibe.materialize.templates import render_project_configuration
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)
from vibe.models.resolution import CapabilityResolution, ResolutionPlan, ResolutionStatus
from vibe.models.risk import RiskLevel


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


def write_configuration(root: Path, current: InventoryResult) -> None:
    blueprint = Blueprint(
        project_name="doctor-fixture",
        goal="Check project health",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        repository_digest="repository-digest",
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
        render_project_configuration(blueprint, plan, current).as_dict().items()
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def test_healthy_configuration_reports_success(tmp_path: Path) -> None:
    current = inventory()
    write_configuration(tmp_path, current)

    report = run_health_checks(tmp_path, current, lambda command: f"/bin/{command}")

    assert report.healthy
    assert report.findings == ()


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
