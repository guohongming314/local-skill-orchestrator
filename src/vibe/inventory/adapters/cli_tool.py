"""Safe deterministic CLI tool discovery and version probing."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vibe.inventory.adapters.base import (
    AdapterDiscovery,
    AdapterProvenance,
    AdapterScanError,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.inventory.taxonomy import provider_capabilities
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)

_VERSION = re.compile(r"(?<![A-Za-z0-9])v?(\d+(?:\.\d+)+(?:[-+.][A-Za-z0-9.-]+)?)")


@dataclass(frozen=True)
class CliToolSpec:
    """Declarative safe probe configuration for one executable."""

    tool_id: str
    executable: str
    version_args: tuple[str, ...]
    provides: tuple[str, ...]
    permissions: frozenset[Permission] = frozenset({Permission.EXECUTE_COMMAND})
    scope: CapabilityScope = CapabilityScope.SYSTEM


@dataclass(frozen=True)
class ProbeResult:
    returncode: int
    stdout: str
    stderr: str


ExecutableResolver = Callable[[str], str | None]
ProbeRunner = Callable[[Sequence[str]], ProbeResult]


class CliToolAdapter:
    """Normalize configured CLI tools while containing all probe failures."""

    adapter_id = "cli-tool"

    def __init__(
        self,
        *,
        specs: tuple[CliToolSpec, ...],
        executable_resolver: ExecutableResolver = shutil.which,
        probe_runner: ProbeRunner | None = None,
    ) -> None:
        self._specs = {spec.tool_id: spec for spec in specs}
        if len(self._specs) != len(specs):
            raise ValueError("CLI tool IDs must be unique")
        self._resolve = executable_resolver
        self._probe = probe_runner or _run_probe

    def discover(self) -> tuple[AdapterDiscovery, ...]:
        return tuple(AdapterDiscovery(locator=tool_id) for tool_id in sorted(self._specs))

    def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
        try:
            spec = self._specs[discovery.locator]
        except KeyError as error:
            raise AdapterScanError(f"unknown CLI tool: {discovery.locator}") from error

        executable = self._resolve(spec.executable)
        version: str | None = None
        details: tuple[str, ...]
        verified = False
        source = executable or spec.executable
        if executable is None:
            details = (f"unavailable:{spec.executable}",)
        else:
            argv = (executable, *spec.version_args)
            try:
                probe = self._probe(argv)
            except Exception as error:
                details = (f"probe_error:{type(error).__name__}:{error}",)
            else:
                output = probe.stdout.strip() or probe.stderr.strip()
                if probe.returncode != 0:
                    details = (f"probe_failed:exit={probe.returncode}:{output}",)
                else:
                    version = _extract_version(output)
                    if version is None:
                        details = ("version_unparseable",)
                    else:
                        details = (f"version:{version}",)
                        verified = True

        provides = (
            tuple(sorted(spec.provides))
            or provider_capabilities(spec.tool_id)
            or ("cli-tools",)
        )
        digest_payload = {
            "executable": spec.executable,
            "permissions": sorted(permission.value for permission in spec.permissions),
            "provides": provides,
            "scope": spec.scope.value,
            "tool_id": spec.tool_id,
            "version": version,
            "verified": verified,
        }
        digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        manifest = CapabilityManifest(
            capability_id=f"cli.{spec.tool_id}",
            name=spec.tool_id,
            kind=CapabilityKind.CLI_TOOL,
            scope=spec.scope,
            source=source,
            provides=provides,
            permissions=spec.permissions,
            version=version,
            content_digest=digest,
            verified=verified,
        )
        return AdapterScanResult(
            manifest=manifest,
            provenance=AdapterProvenance(adapter_id=self.adapter_id, locator=source),
            verification=AdapterVerification(verified=verified, details=details),
        )


def _run_probe(argv: Sequence[str]) -> ProbeResult:
    completed = subprocess.run(
        list(argv),
        capture_output=True,
        check=False,
        shell=False,
        text=True,
        timeout=5,
    )
    return ProbeResult(completed.returncode, completed.stdout, completed.stderr)


def _extract_version(output: str) -> str | None:
    match = _VERSION.search(output)
    return None if match is None else match.group(1)
