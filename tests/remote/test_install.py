from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.service import InventoryResult, InventoryService
from vibe.models.capability import CapabilityScope
from vibe.remote.install import (
    ApprovalRequiredError,
    InstallFile,
    InstallPackage,
    InstallVerificationError,
    build_install_plan,
    execute_install,
)
from vibe.remote.models import (
    CapabilityKind,
    PermissionLevel,
    Provenance,
    PublisherVerification,
    RemoteCandidate,
    SourceTier,
)


def _candidate(*, permission_level: PermissionLevel = PermissionLevel.L1) -> RemoteCandidate:
    skill = _skill_content()
    digest = f"sha256:{hashlib.sha256(skill.encode()).hexdigest()}"
    return RemoteCandidate(
        candidate_ref="registry:agent-skill/browser-testing@1.2.3",
        name="browser-testing",
        kind=CapabilityKind.AGENT_SKILL,
        provides=("browser.testing",),
        version="1.2.3",
        digest=digest,
        publisher="example-org",
        source_tier=SourceTier.VERIFIED_PUBLISHER,
        provenance=Provenance(
            source="registry:agent-skill/browser-testing@1.2.3",
            publisher="example-org",
            digest=digest,
            source_verified=True,
            publisher_verified=True,
            publisher_verification=PublisherVerification.ALLOWLIST,
            digest_verified=True,
            permission_level=permission_level,
            reason="verified fixture publisher and immutable digest",
        ),
    )


def _skill_content() -> str:
    return """---
name: browser-testing
description: Browser testing workflow
---

Use the browser test runner.
"""


def _package() -> InstallPackage:
    return InstallPackage(
        files=(
            InstallFile(
                path=".agents/skills/browser-testing/SKILL.md",
                content=_skill_content(),
            ),
        ),
    )


def _scan(root: Path) -> InventoryResult:
    return InventoryService().scan(
        (
            AgentSkillAdapter(
                roots=(
                    SkillRoot(
                        path=root / ".agents" / "skills",
                        scope=CapabilityScope.PROJECT,
                    ),
                )
            ),
        )
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_successful_install_pins_digest_and_inventory_resolves_capability(
    tmp_path: Path,
) -> None:
    plan = build_install_plan(tmp_path, _candidate(), _package())

    result = execute_install(plan, approved=True, inventory_scan=_scan)

    lock = yaml.safe_load((tmp_path / ".ai-project/capabilities.lock").read_text())
    provider = next(
        item
        for item in lock["providers"]
        if item["provider_id"] == "skill.browser-testing"
    )
    assert provider["version"] == "1.2.3"
    provenance = _candidate().provenance
    assert provenance is not None
    assert provider["content_digest"] == provenance.digest
    assert provider["publisher"] == "example-org"
    assert provider["source_verified"] is True
    assert any(
        item.manifest.capability_id == "skill.browser-testing"
        for item in result.inventory.capabilities
    )


def test_post_install_verification_failure_rolls_back_without_residue(
    tmp_path: Path,
) -> None:
    (tmp_path / ".ai-project").mkdir()
    (tmp_path / ".ai-project/capabilities.lock").write_text("original-lock\n")
    (tmp_path / "keep.txt").write_text("original\n")
    before = _tree_bytes(tmp_path)
    plan = build_install_plan(tmp_path, _candidate(), _package())

    def fail_verification(_root: Path) -> InventoryResult:
        raise InstallVerificationError("injected post-install verification failure")

    with pytest.raises(InstallVerificationError, match="injected"):
        execute_install(plan, approved=True, inventory_scan=fail_verification)

    assert _tree_bytes(tmp_path) == before
    assert not any(path.name.startswith(".vibe-") for path in tmp_path.iterdir())


def test_install_without_approval_changes_nothing(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("original\n")
    before = _tree_bytes(tmp_path)
    plan = build_install_plan(tmp_path, _candidate(), _package())

    with pytest.raises(ApprovalRequiredError, match="approval"):
        execute_install(plan, approved=False, inventory_scan=_scan)

    assert _tree_bytes(tmp_path) == before
