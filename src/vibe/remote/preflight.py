"""One-time sandbox preflight for newly installed remote capabilities."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from vibe.remote.models import RemoteCandidate


class PreflightError(RuntimeError):
    """A capability behaved outside its declared permissions during preflight."""


class PreflightFile(Protocol):
    path: str
    content: str


@dataclass(frozen=True)
class PreflightResult:
    tools: tuple[str, ...]
    observed_permissions: tuple[str, ...]


_PERMISSION_ALIASES = {
    "network": "network",
    "network-access": "network",
    "filesystem-write": "filesystem-write",
    "filesystem.write": "filesystem-write",
    "fs-write": "filesystem-write",
}


def run_preflight(
    candidate: RemoteCandidate,
    files: Sequence[PreflightFile],
    argv: tuple[str, ...],
) -> PreflightResult:
    """Launch a capability with a temporary home and audit its tools and behavior."""
    declared = {
        normalized
        for permission in candidate.permissions_as_declared
        if (normalized := _PERMISSION_ALIASES.get(permission.lower())) is not None
    }
    if not argv:
        return PreflightResult(tools=tuple(sorted(candidate.provides)), observed_permissions=())

    with tempfile.TemporaryDirectory(prefix="vibe-preflight-") as temporary:
        sandbox = Path(temporary)
        package_root = sandbox / "package"
        home = sandbox / "home"
        hook_root = sandbox / "hook"
        package_root.mkdir()
        home.mkdir()
        hook_root.mkdir()
        for item in files:
            target = _safe_target(package_root, item.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item.content, encoding="utf-8")

        audit_path = sandbox / "audit.jsonl"
        (hook_root / "sitecustomize.py").write_text(_audit_hook_source(), encoding="utf-8")
        command = tuple(part.replace("{package_root}", str(package_root)) for part in argv)
        environment = {
            "HOME": str(home),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(hook_root),
            "VIBE_PREFLIGHT_AUDIT": str(audit_path),
            "VIBE_PREFLIGHT_ROOT": str(sandbox),
            "VIBE_PREFLIGHT_ALLOW_NETWORK": "1" if "network" in declared else "0",
        }
        completed = subprocess.run(
            command,
            cwd=sandbox,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        observed = _read_observed(audit_path)
        undeclared = sorted(observed - declared)
        if undeclared:
            raise PreflightError(
                "undeclared behavior during preflight: " + ", ".join(undeclared)
            )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
            raise PreflightError(f"capability preflight process failed: {detail}")
        tools = _parse_tools(completed.stdout)
        declared_tools = tuple(sorted(candidate.provides))
        if declared_tools and tools != declared_tools:
            raise PreflightError(
                f"preflight tool inventory differs from declaration: expected "
                f"{declared_tools!r}, observed {tools!r}"
            )
        return PreflightResult(
            tools=tools,
            observed_permissions=tuple(sorted(observed)),
        )


def _safe_target(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise PreflightError(f"unsafe package path for preflight: {relative}")
    target = (root / Path(*pure.parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise PreflightError(f"unsafe package path for preflight: {relative}")
    return target


def _parse_tools(stdout: str) -> tuple[str, ...]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise PreflightError("capability preflight did not enumerate tools")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise PreflightError("capability preflight returned invalid tool inventory") from error
    tools = payload.get("tools") if isinstance(payload, dict) else None
    if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
        raise PreflightError("capability preflight returned invalid tool inventory")
    return tuple(sorted(set(tools)))


def _read_observed(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    observed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        permission = payload.get("permission") if isinstance(payload, dict) else None
        if isinstance(permission, str):
            observed.add(permission)
    return observed


def _audit_hook_source() -> str:
    return '''import json
import os
import pathlib
import sys

_AUDIT = pathlib.Path(os.environ["VIBE_PREFLIGHT_AUDIT"])
_ROOT = pathlib.Path(os.environ["VIBE_PREFLIGHT_ROOT"]).resolve()
_ALLOW_NETWORK = os.environ["VIBE_PREFLIGHT_ALLOW_NETWORK"] == "1"


def _record(permission):
    with _AUDIT.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"permission": permission}) + "\\n")


def _hook(event, args):
    if event in {"socket.connect", "socket.bind"}:
        _record("network")
        if not _ALLOW_NETWORK:
            raise PermissionError("network denied by vibe preflight")
    if event == "open" and len(args) > 1:
        raw_path, mode = args[0], args[1]
        if isinstance(raw_path, (str, bytes, os.PathLike)) and isinstance(mode, str):
            if any(flag in mode for flag in ("w", "a", "x", "+")):
                path = pathlib.Path(raw_path).resolve()
                if not path.is_relative_to(_ROOT):
                    _record("filesystem-write")
                    raise PermissionError("filesystem write denied by vibe preflight")

sys.addaudithook(_hook)
'''
