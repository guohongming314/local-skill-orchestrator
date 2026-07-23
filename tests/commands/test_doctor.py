from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import vibe.commands.doctor as doctor_module
import vibe.commands.init as init_module
from vibe.cli import app
from vibe.commands.doctor import exit_code_for_report
from vibe.commands.init import _project_changeset
from vibe.commands.project_plan import ProjectPlan, build_project_plan
from vibe.doctor.report import DoctorFinding, DoctorReport, Severity
from vibe.inspect.repository import inspect_repository
from vibe.inventory.service import InventoryResult
from vibe.materialize.writer import apply_changeset
from vibe.models.blueprint import Blueprint, LifecycleStage
from vibe.models.decisions import NetworkDecision, NetworkPolicy, ProjectDecisions
from vibe.models.repository import RepositorySnapshot
from vibe.models.risk import RiskLevel
from vibe.remote.models import RemoteCandidate
from vibe.remote.scoring import CandidateEvidence

runner = CliRunner()


def initialized_project(root: Path) -> None:
    blueprint = Blueprint(
        project_name="doctor-cli-fixture",
        goal="Verify project health",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        preferences={"candidate_decisions": "*=defer"},
        decisions=ProjectDecisions(
            network_policy=NetworkDecision(value=NetworkPolicy.DENIED)
        ),
        repository_digest=inspect_repository(root).source_digest,
    )
    apply_changeset(_project_changeset(root, blueprint))


def test_doctor_reports_healthy_project_in_human_and_stable_json(tmp_path: Path) -> None:
    initialized_project(tmp_path)

    human = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
    machine = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])

    assert human.exit_code == 0
    assert "healthy" in human.stdout.lower()
    assert machine.exit_code == 0
    assert json.loads(machine.stdout) == {
        "findings": [],
        "schema_version": "1",
        "status": "healthy",
    }


def test_doctor_builds_one_coherent_project_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialized_project(tmp_path)
    calls = 0

    def counted_build(
        root: Path,
        blueprint: Blueprint,
        repository: RepositorySnapshot,
        *,
        inventory: InventoryResult | None = None,
        remote_candidates: tuple[RemoteCandidate, ...] = (),
        remote_evidence: dict[str, CandidateEvidence] | None = None,
        rejected_remote_candidates: frozenset[str] = frozenset(),
    ) -> ProjectPlan:
        nonlocal calls
        calls += 1
        return build_project_plan(
            root,
            blueprint,
            repository,
            inventory=inventory,
            remote_candidates=remote_candidates,
            remote_evidence=remote_evidence,
            rejected_remote_candidates=rejected_remote_candidates,
        )

    def unexpected_second_build(*args: object, **kwargs: object) -> None:
        raise AssertionError("doctor must pass the complete project plan to materialization")

    monkeypatch.setattr(doctor_module, "build_project_plan", counted_build)
    monkeypatch.setattr(init_module, "build_project_plan", unexpected_second_build)

    result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    assert calls == 1


def test_doctor_invalid_configuration_exits_error_without_leaking_value(
    tmp_path: Path,
) -> None:
    initialized_project(tmp_path)
    secret = "not-for-output"
    policy = tmp_path / ".ai-project/policy.yaml"
    payload = yaml.safe_load(policy.read_text(encoding="utf-8"))
    payload["secret"] = secret
    policy.write_text(yaml.safe_dump(payload), encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])

    assert result.exit_code == 2
    output = json.loads(result.stdout)
    assert output["status"] == "error"
    assert "configuration.invalid" in {item["code"] for item in output["findings"]}
    assert secret not in result.stdout


def test_doctor_exit_codes_cover_warning_and_error_severity() -> None:
    warning = DoctorReport(
        (
            DoctorFinding(
                code="warning.fixture",
                severity=Severity.WARNING,
                summary="Review fixture.",
                evidence=("fixture",),
                remediation="Review it.",
            ),
        )
    )
    error = DoctorReport(
        (
            DoctorFinding(
                code="error.fixture",
                severity=Severity.ERROR,
                summary="Fix fixture.",
                evidence=("fixture",),
                remediation="Fix it.",
            ),
        )
    )

    assert exit_code_for_report(DoctorReport(())) == 0
    assert exit_code_for_report(warning) == 1
    assert exit_code_for_report(error) == 2
