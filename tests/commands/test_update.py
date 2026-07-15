from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import yaml
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


def _bundle(
    path: Path,
    *,
    version: str,
    permission_level: PermissionLevel,
    manifest_name: str = "browser-testing",
) -> Path:
    content = f"""---
name: {manifest_name}
description: Browser testing workflow {version}
---

Use browser tests from version {version}.
"""
    digest = f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"
    candidate = RemoteCandidate(
        candidate_ref=f"registry:browser-testing@{version}",
        name="browser-testing",
        kind=CapabilityKind.AGENT_SKILL,
        provides=("browser.testing",),
        version=version,
        digest=digest,
        publisher="example-org",
        source_tier=SourceTier.VERIFIED_PUBLISHER,
        provenance=Provenance(
            source=f"registry:browser-testing@{version}",
            publisher="example-org",
            digest=digest,
            source_verified=True,
            publisher_verified=True,
            publisher_verification=PublisherVerification.ALLOWLIST,
            digest_verified=True,
            permission_level=permission_level,
            reason="verified update fixture",
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


def _install(root: Path, bundle: Path) -> None:
    result = runner.invoke(
        app,
        [
            "install",
            "browser-testing",
            "--path",
            str(root),
            "--candidate-file",
            str(bundle),
            "--approve",
        ],
    )
    assert result.exit_code == 0, result.stdout


def _provider(root: Path) -> dict[str, object]:
    lock = yaml.safe_load((root / ".ai-project/capabilities.lock").read_text())
    providers = [
        item for item in lock["providers"] if item["provider_id"] == "skill.browser-testing"
    ]
    assert len(providers) == 1
    return cast(dict[str, object], providers[0])


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        item.relative_to(root).as_posix(): item.read_bytes()
        for item in sorted(root.rglob("*"))
        if item.is_file() and not item.name.startswith("candidate-")
    }


def test_same_permission_upgrade_lands_with_one_approval(tmp_path: Path) -> None:
    old = _bundle(
        tmp_path / "candidate-old.json",
        version="1.2.3",
        permission_level=PermissionLevel.L1,
    )
    new = _bundle(
        tmp_path / "candidate-new.json",
        version="1.3.0",
        permission_level=PermissionLevel.L1,
    )
    _install(tmp_path, old)

    result = runner.invoke(
        app,
        [
            "update",
            "browser-testing",
            "--path",
            str(tmp_path),
            "--candidate-file",
            str(new),
            "--approve",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "1.2.3 -> 1.3.0" in result.stdout
    assert _provider(tmp_path)["version"] == "1.3.0"


def test_widened_permission_upgrade_blocks_until_reapproved(tmp_path: Path) -> None:
    old = _bundle(
        tmp_path / "candidate-old.json",
        version="1.2.3",
        permission_level=PermissionLevel.L1,
    )
    new = _bundle(
        tmp_path / "candidate-new.json",
        version="2.0.0",
        permission_level=PermissionLevel.L2,
    )
    _install(tmp_path, old)

    blocked = runner.invoke(
        app,
        [
            "update",
            "browser-testing",
            "--path",
            str(tmp_path),
            "--candidate-file",
            str(new),
        ],
    )

    assert blocked.exit_code != 0
    assert "permission expansion" in blocked.stdout.lower()
    assert "L1 -> L2" in blocked.stdout
    assert _provider(tmp_path)["version"] == "1.2.3"

    approved = runner.invoke(
        app,
        [
            "update",
            "browser-testing",
            "--path",
            str(tmp_path),
            "--candidate-file",
            str(new),
            "--approve",
        ],
    )

    assert approved.exit_code == 0, approved.stdout
    assert _provider(tmp_path)["version"] == "2.0.0"
    assert _provider(tmp_path)["permission_level"] == "L2"


def test_failure_mid_upgrade_restores_old_version(tmp_path: Path) -> None:
    old = _bundle(
        tmp_path / "candidate-old.json",
        version="1.2.3",
        permission_level=PermissionLevel.L1,
    )
    broken = _bundle(
        tmp_path / "candidate-broken.json",
        version="1.3.0",
        permission_level=PermissionLevel.L1,
        manifest_name="wrong-capability",
    )
    _install(tmp_path, old)
    before = _snapshot(tmp_path)

    result = runner.invoke(
        app,
        [
            "update",
            "browser-testing",
            "--path",
            str(tmp_path),
            "--candidate-file",
            str(broken),
            "--approve",
        ],
    )

    assert result.exit_code != 0
    assert "did not resolve" in str(result.exception)
    assert _snapshot(tmp_path) == before
    assert _provider(tmp_path)["version"] == "1.2.3"


def test_check_lists_newer_cached_candidate_without_writing(tmp_path: Path) -> None:
    old = _bundle(
        tmp_path / "candidate-old.json",
        version="1.2.3",
        permission_level=PermissionLevel.L1,
    )
    new = _bundle(
        tmp_path / "candidate-new.json",
        version="1.3.0",
        permission_level=PermissionLevel.L1,
    )
    _install(tmp_path, old)
    before = _snapshot(tmp_path)

    result = runner.invoke(
        app,
        [
            "update",
            "browser-testing",
            "--path",
            str(tmp_path),
            "--candidate-file",
            str(new),
            "--check",
            "--offline",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "1.2.3 -> 1.3.0" in result.stdout
    assert _snapshot(tmp_path) == before
    assert _provider(tmp_path)["version"] == "1.2.3"
