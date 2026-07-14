from __future__ import annotations

import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from vibe.cli import app
from vibe.remote.install import InstallFile, InstallPackage
from vibe.remote.models import (
    CapabilityKind,
    PermissionLevel,
    Provenance,
    PublisherVerification,
    RemoteCandidate,
    SourceTier,
)

runner = CliRunner()


def _bundle(path: Path) -> Path:
    content = """---
name: browser-testing
description: Browser testing workflow
---

Use browser tests.
"""
    digest = f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"
    candidate = RemoteCandidate(
        candidate_ref="registry:browser-testing@1.2.3",
        name="browser-testing",
        kind=CapabilityKind.AGENT_SKILL,
        provides=("browser.testing",),
        version="1.2.3",
        digest=digest,
        publisher="example-org",
        source_tier=SourceTier.VERIFIED_PUBLISHER,
        provenance=Provenance(
            source="registry:browser-testing@1.2.3",
            publisher="example-org",
            digest=digest,
            source_verified=True,
            publisher_verified=True,
            publisher_verification=PublisherVerification.ALLOWLIST,
            digest_verified=True,
            permission_level=PermissionLevel.L1,
            reason="verified fixture",
        ),
    )
    package = InstallPackage(
        files=(
            InstallFile(
                path=".agents/skills/browser-testing/SKILL.md",
                content=content,
            ),
        )
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
    return path


def test_install_without_approval_exits_nonzero_and_changes_nothing(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "candidate.json")
    before = bundle.read_bytes()

    result = runner.invoke(
        app,
        [
            "install",
            "browser-testing",
            "--path",
            str(tmp_path),
            "--candidate-file",
            str(bundle),
        ],
    )

    assert result.exit_code != 0
    assert "approval" in result.stdout.lower()
    assert bundle.read_bytes() == before
    assert not (tmp_path / ".agents").exists()
    assert not (tmp_path / ".ai-project").exists()


def test_install_dry_run_reuses_changeset_renderer_and_writes_nothing(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "candidate.json")

    result = runner.invoke(
        app,
        [
            "install",
            "browser-testing",
            "--path",
            str(tmp_path),
            "--candidate-file",
            str(bundle),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "ChangeSet" in result.stdout
    assert ".ai-project/capabilities.lock" in result.stdout
    assert ".agents/skills/browser-testing/SKILL.md" in result.stdout
    assert not (tmp_path / ".agents").exists()
    assert not (tmp_path / ".ai-project").exists()
