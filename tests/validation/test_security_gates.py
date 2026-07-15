from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pydantic import BaseModel
from typer.testing import CliRunner

from vibe.cli import app
from vibe.codex.approvals import (
    ApprovalKind,
    ApprovalOutcome,
    ApprovalPolicy,
    ApprovalRequest,
    decide_approval,
)
from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.service import InventoryService
from vibe.models.capability import CapabilityScope, Permission
from vibe.models.capsule import ContextCapsule, SourceReference
from vibe.models.outcome import TaskOutcome
from vibe.models.risk import RiskLevel
from vibe.policy.org import OrgPolicy
from vibe.remote.install import InstallFile, InstallPackage, build_install_plan
from vibe.remote.models import (
    CapabilityKind,
    PermissionLevel,
    Provenance,
    PublisherVerification,
    RemoteCandidate,
    SourceTier,
)
from vibe.remote.provenance import DigestMismatchError
from vibe.remote.scan import RiskCategory, scan_skill
from vibe.remote.scoring import CandidateEvidence, ScoringContext, rank_candidates
from vibe.resolver.policy import ResolverPolicy, remote_org_filter_reason

pytestmark = pytest.mark.validation

_FIXTURES = Path(__file__).with_name("fixtures")
_SECRET = "VIBE_SECURITY_SEEDED_TOKEN_145"
_RUNNER = CliRunner()


def _bundle(
    path: Path,
    *,
    version: str = "1.0.0",
    permission_level: PermissionLevel = PermissionLevel.L1,
    content: str | None = None,
) -> tuple[Path, RemoteCandidate, InstallPackage]:
    skill = content or "---\nname: safe-skill\ndescription: Safe fixture\n---\n\nUse tests.\n"
    digest = f"sha256:{hashlib.sha256(skill.encode()).hexdigest()}"
    candidate = RemoteCandidate(
        candidate_ref=f"registry:safe-skill@{version}",
        name="safe-skill",
        kind=CapabilityKind.AGENT_SKILL,
        provides=("testing",),
        version=version,
        digest=digest,
        publisher="fixture-publisher",
        source_tier=SourceTier.VERIFIED_PUBLISHER,
        provenance=Provenance(
            source=f"registry:safe-skill@{version}",
            publisher="fixture-publisher",
            digest=digest,
            source_verified=True,
            publisher_verified=True,
            publisher_verification=PublisherVerification.ALLOWLIST,
            digest_verified=True,
            permission_level=permission_level,
            reason="security validation fixture",
        ),
    )
    package = InstallPackage(
        files=(InstallFile(path=".agents/skills/safe-skill/SKILL.md", content=skill),)
    )
    path.write_text(
        json.dumps(
            {
                "candidate": candidate.model_dump(mode="json"),
                "package": package.model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )
    return path, candidate, package


def _serialized(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif is_dataclass(value) and not isinstance(value, type):
        value = asdict(cast(Any, value))
    return json.dumps(value, sort_keys=True, default=str)


def test_install_bypasses_fail_closed_with_explainable_refusals(tmp_path: Path) -> None:
    bundle, candidate, package = _bundle(tmp_path / "candidate.json")

    unapproved = _RUNNER.invoke(
        app,
        ["install", "safe-skill", "--path", str(tmp_path), "--candidate-file", str(bundle)],
    )
    assert unapproved.exit_code != 0
    assert "approval" in unapproved.stdout.lower()
    assert not (tmp_path / ".agents").exists()

    tampered = package.model_copy(
        update={"files": (package.files[0].model_copy(update={"content": "tampered"}),)}
    )
    with pytest.raises(DigestMismatchError, match="content digest mismatch"):
        build_install_plan(tmp_path, candidate, tampered)

    l4_candidate = candidate.model_copy(
        update={
            "provenance": cast(Provenance, candidate.provenance).model_copy(
                update={"permission_level": PermissionLevel.L4}
            )
        }
    )
    with pytest.raises(ValueError, match="L4 candidates are blocked"):
        build_install_plan(tmp_path, l4_candidate, package)

    approval_request = ApprovalRequest(
        request_id=145,
        method="item/permissions/requestApproval",
        kind=ApprovalKind.PERMISSIONS,
        thread_id="security-validation",
        turn_id="install-bypass",
        item_id="safe-skill",
        tool_name=None,
        requested_permissions={"install": True},
    )
    decision = decide_approval(approval_request, ApprovalPolicy())
    assert decision.outcome is ApprovalOutcome.DENY
    assert decision.audit.outcome is ApprovalOutcome.DENY


def test_permission_expansion_and_org_policy_bypasses_are_audited(tmp_path: Path) -> None:
    old_bundle, _, _ = _bundle(tmp_path / "old.json")
    installed = _RUNNER.invoke(
        app,
        [
            "install",
            "safe-skill",
            "--path",
            str(tmp_path),
            "--candidate-file",
            str(old_bundle),
            "--approve",
        ],
    )
    assert installed.exit_code == 0, installed.stdout
    new_bundle, _, _ = _bundle(
        tmp_path / "new.json", version="2.0.0", permission_level=PermissionLevel.L2
    )

    expanded = _RUNNER.invoke(
        app,
        ["update", "safe-skill", "--path", str(tmp_path), "--candidate-file", str(new_bundle)],
    )
    assert expanded.exit_code != 0
    assert "permission expansion requires re-approval" in expanded.stdout.lower()
    lock = yaml.safe_load((tmp_path / ".ai-project/capabilities.lock").read_text())
    provider = next(item for item in lock["providers"] if item["provider_id"] == "skill.safe-skill")
    assert provider["version"] == "1.0.0"

    policy = ApprovalPolicy({ApprovalKind.PERMISSIONS: ApprovalOutcome.DENY})
    decision = decide_approval(
        ApprovalRequest(
            request_id=146,
            method="item/permissions/requestApproval",
            kind=ApprovalKind.PERMISSIONS,
            thread_id="security-validation",
            turn_id="permission-expansion",
            item_id="safe-skill",
            tool_name=None,
            requested_permissions={"network": True},
        ),
        policy,
    )
    assert decision.audit.outcome is ApprovalOutcome.DENY

    _, policy_candidate, _ = _bundle(tmp_path / "policy-candidate.json", version="3.0.0")
    user_preference = policy_candidate.name
    org_policy = OrgPolicy(blocked_capability_ids=frozenset({user_preference}))
    refusal = remote_org_filter_reason(
        policy_candidate,
        ResolverPolicy(org_policy=org_policy, org_policy_path="org-policy.yaml"),
    )
    assert refusal == "blocked by org policy org-policy.yaml"
    org_decision = decide_approval(
        ApprovalRequest(
            request_id=148,
            method="item/permissions/requestApproval",
            kind=ApprovalKind.PERMISSIONS,
            thread_id="security-validation",
            turn_id="org-policy-bypass",
            item_id=user_preference,
            tool_name=None,
            requested_permissions={"user_preference": user_preference},
        ),
        ApprovalPolicy(),
    )
    assert org_decision.audit.outcome is ApprovalOutcome.DENY


def test_malicious_skill_is_scanned_rejected_and_never_recommended() -> None:
    skill_dir = _FIXTURES / "malicious-skill"
    scan = scan_skill(skill_dir)
    categories = {flag.category for flag in scan.flags}
    assert RiskCategory.INSTRUCTION_INJECTION in categories
    assert RiskCategory.CREDENTIAL_REFERENCE in categories
    assert any(flag.auto_blocking for flag in scan.flags)
    assert _SECRET not in _serialized(scan)
    assert "[REDACTED]" in _serialized(scan)

    content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    digest = f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"
    candidate = RemoteCandidate(
        candidate_ref="community:malicious-security-fixture@1.0.0",
        name="malicious-security-fixture",
        kind=CapabilityKind.AGENT_SKILL,
        provides=("testing",),
        version="1.0.0",
        digest=digest,
        source_tier=SourceTier.COMMUNITY,
        provenance=Provenance(
            source="community:malicious-security-fixture@1.0.0",
            digest=digest,
            source_verified=False,
            publisher_verified=False,
            publisher_verification=PublisherVerification.UNVERIFIED,
            digest_verified=True,
            permission_level=max(
                (flag.level for flag in scan.flags), key=lambda level: level.value
            ),
            reason="static scan found auto-blocking instruction injection",
        ),
    )
    ranked = rank_candidates(
        (candidate,),
        ScoringContext(
            requirement="testing",
            target_platforms=("linux",),
            project_risk_level=RiskLevel.MEDIUM,
        ),
        evidence={
            candidate.candidate_ref: CandidateEvidence(
                scan_flags=tuple(flag.category.value for flag in scan.flags)
            )
        },
    )
    assert ranked == ()
    package = InstallPackage(
        files=(InstallFile(path=".agents/skills/malicious/SKILL.md", content=content),)
    )
    with pytest.raises(ValueError, match="L4 candidates are blocked"):
        build_install_plan(Path.cwd(), candidate, package)


def test_seeded_credentials_never_appear_in_serialized_artifacts(tmp_path: Path) -> None:
    skill_root = tmp_path / ".agents" / "skills" / "safe-reader"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: safe-reader\ndescription: Reads public files\n---\n\n"
        "See [credentials](credentials.json).\n",
        encoding="utf-8",
    )
    (skill_root / "credentials.json").write_text(_SECRET, encoding="utf-8")
    (tmp_path / ".env").write_text(f"API_TOKEN={_SECRET}\n", encoding="utf-8")

    inventory = InventoryService().scan(
        [
            AgentSkillAdapter(
                roots=(SkillRoot(tmp_path / ".agents" / "skills", CapabilityScope.PROJECT),)
            )
        ]
    )
    capsule = ContextCapsule(
        task_id="security-145",
        intent="Validate security gates",
        scope=("tests/validation",),
        acceptance_criteria=("No secrets leak",),
        current_phase="verify",
        selected_capability_ids=tuple(
            item.manifest.capability_id for item in inventory.capabilities
        ),
        requested_permissions=(Permission.READ_PROJECT,),
        sources=(SourceReference(source_id="inventory", digest=inventory.inventory_digest),),
        invalidation_conditions=("inventory digest changes",),
        token_budget=512,
    )
    outcome = TaskOutcome(
        task_type="security-validation",
        workflow="rigorous",
        capabilities_used=capsule.selected_capability_ids,
        verification_passed=True,
        user_rework=False,
    )
    refusal_audit = decide_approval(
        ApprovalRequest(
            request_id=147,
            method="item/commandExecution/requestApproval",
            kind=ApprovalKind.COMMAND,
            thread_id="security-validation",
            turn_id="secret-probe",
            item_id="probe",
            tool_name=None,
            requested_permissions=None,
        ),
        ApprovalPolicy(),
    ).audit
    validation_report: dict[str, Any] = {
        "inventory": {
            "capabilities": [
                item.manifest.model_dump(mode="json") for item in inventory.capabilities
            ],
            "diagnostics": [asdict(item) for item in inventory.diagnostics],
            "digest": inventory.inventory_digest,
        },
        "capsule": capsule.model_dump(mode="json"),
        "outcome": outcome.model_dump(mode="json"),
        "audit_events": [asdict(refusal_audit)],
        "status": "PASS",
    }
    artifacts = (
        _serialized(validation_report["inventory"]),
        _serialized(capsule),
        _serialized(outcome),
        _serialized(refusal_audit),
        _serialized(validation_report),
        _serialized(scan_skill(_FIXTURES / "malicious-skill")),
    )
    assert all(_SECRET not in artifact for artifact in artifacts)
