from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import yaml

from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.service import InventoryResult, InventoryService
from vibe.models.capability import CapabilityScope
from vibe.remote.install import InstallFile, InstallPackage, build_install_plan, execute_install
from vibe.remote.models import (
    CapabilityKind,
    PermissionLevel,
    Provenance,
    PublisherVerification,
    RemoteCandidate,
    SourceTier,
)
from vibe.remote.preflight import PreflightError, PreflightResult, run_preflight

_SKILL = """---
name: sandboxed-server
description: Sandboxed fixture server
---

Use the fixture server.
"""


def _server(*, network_attempt: bool, outside_write: bool = False) -> str:
    behavior = """
import socket
socket.create_connection(("127.0.0.1", 9), timeout=0.1)
""" if network_attempt else ""
    write_behavior = """
from pathlib import Path
Path("/tmp/vibe-preflight-escape").write_text("escaped")
""" if outside_write else ""
    return f"""import json
{behavior}
{write_behavior}
print(json.dumps({{"tools": ["fixture.echo"]}}), flush=True)
"""


def _package(
    *, network_attempt: bool = False, outside_write: bool = False
) -> InstallPackage:
    return InstallPackage(
        files=(
            InstallFile(path=".agents/skills/sandboxed-server/SKILL.md", content=_SKILL),
            InstallFile(
                path="bin/fixture_server.py",
                content=_server(
                    network_attempt=network_attempt, outside_write=outside_write
                ),
            ),
        ),
        preflight_argv=(sys.executable, "{package_root}/bin/fixture_server.py"),
    )


def _digest(package: InstallPackage) -> str:
    content = b"".join(
        item.path.encode() + b"\0" + item.content.encode() + b"\0"
        for item in sorted(package.files, key=lambda file: file.path)
    )
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _candidate(package: InstallPackage) -> RemoteCandidate:
    digest = _digest(package)
    return RemoteCandidate(
        candidate_ref="registry:agent-skill/sandboxed-server@1.0.0",
        name="sandboxed-server",
        kind=CapabilityKind.AGENT_SKILL,
        provides=("fixture.echo",),
        version="1.0.0",
        digest=digest,
        publisher="example-org",
        permissions_as_declared=(),
        source_tier=SourceTier.VERIFIED_PUBLISHER,
        provenance=Provenance(
            source="registry:agent-skill/sandboxed-server@1.0.0",
            publisher="example-org",
            digest=digest,
            source_verified=True,
            publisher_verified=True,
            publisher_verification=PublisherVerification.ALLOWLIST,
            digest_verified=True,
            permission_level=PermissionLevel.L2,
            reason="verified fixture publisher and immutable digest",
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


def test_compliant_fixture_passes_preflight_and_enumerates_tools(tmp_path: Path) -> None:
    package = _package()
    result = run_preflight(_candidate(package), package.files, package.preflight_argv)

    assert result.tools == ("fixture.echo",)
    assert result.observed_permissions == ()


def test_undeclared_network_attempt_fails_preflight_and_rolls_back_install(
    tmp_path: Path,
) -> None:
    (tmp_path / "keep.txt").write_text("original\n")
    before = _tree_bytes(tmp_path)
    package = _package(network_attempt=True)
    plan = build_install_plan(tmp_path, _candidate(package), package)

    with pytest.raises(PreflightError, match=r"undeclared.*network"):
        execute_install(plan, approved=True, inventory_scan=_scan)

    assert _tree_bytes(tmp_path) == before


def test_filesystem_write_outside_sandbox_fails_preflight(tmp_path: Path) -> None:
    package = _package(outside_write=True)

    with pytest.raises(PreflightError, match=r"undeclared.*filesystem-write"):
        run_preflight(_candidate(package), package.files, package.preflight_argv)


def test_passed_preflight_is_skipped_for_identical_digest(tmp_path: Path) -> None:
    package = _package()
    candidate = _candidate(package)
    calls = 0

    def counted_preflight(
        candidate: RemoteCandidate,
        files: tuple[InstallFile, ...],
        argv: tuple[str, ...],
    ) -> PreflightResult:
        nonlocal calls
        calls += 1
        return run_preflight(candidate, files, argv)

    first = build_install_plan(tmp_path, candidate, package)
    execute_install(first, approved=True, inventory_scan=_scan, preflight_run=counted_preflight)
    second = build_install_plan(tmp_path, candidate, package)
    result = execute_install(
        second, approved=True, inventory_scan=_scan, preflight_run=counted_preflight
    )

    lock = yaml.safe_load((tmp_path / ".ai-project/capabilities.lock").read_text())
    provider = next(
        item
        for item in lock["providers"]
        if item["provider_id"] == "skill.sandboxed-server"
    )
    assert calls == 1
    assert result.applied_paths == ()
    assert provider["preflight"]["status"] == "passed"
    provenance = candidate.provenance
    assert provenance is not None
    assert provider["preflight"]["digest"] == provenance.digest
    assert provider["preflight"]["tools"] == ["fixture.echo"]
