"""Offline static safety scanning for remote skills and MCP metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from vibe.remote.models import PermissionLevel


class RiskCategory(StrEnum):
    COMMAND_EXECUTION = "command-execution"
    NETWORK_ACCESS = "network-access"
    CREDENTIAL_REFERENCE = "credential-access"
    INSTRUCTION_INJECTION = "instruction-injection"


class McpPermission(StrEnum):
    EXECUTE = "execute"
    NETWORK = "network"
    FILESYSTEM_WRITE = "filesystem-write"


@dataclass(frozen=True)
class SourceLocation:
    path: str
    line: int
    column: int


@dataclass(frozen=True)
class RiskFlag:
    category: RiskCategory
    level: PermissionLevel
    source: SourceLocation
    evidence: str
    auto_blocking: bool = False


@dataclass(frozen=True)
class SkillScanResult:
    flags: tuple[RiskFlag, ...] = ()


@dataclass(frozen=True)
class McpPermissionSummary:
    tools: tuple[str, ...] = ()
    transports: tuple[str, ...] = ()
    permissions: tuple[McpPermission, ...] = ()


@dataclass(frozen=True)
class _Pattern:
    category: RiskCategory
    level: PermissionLevel
    expression: re.Pattern[str]
    auto_blocking: bool = False


_PATTERNS = (
    _Pattern(
        RiskCategory.COMMAND_EXECUTION,
        PermissionLevel.L2,
        re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba|z|k)?sh\b|\beval\s+", re.IGNORECASE),
    ),
    _Pattern(
        RiskCategory.NETWORK_ACCESS,
        PermissionLevel.L2,
        re.compile(r"\b(?:curl|wget)\b\s+|\b(?:requests|urllib3?|fetch)\s*[.(]", re.IGNORECASE),
    ),
    _Pattern(
        RiskCategory.CREDENTIAL_REFERENCE,
        PermissionLevel.L3,
        re.compile(
            r"(?:\$\{?)?(?:AWS_SECRET_ACCESS_KEY|GITHUB_TOKEN|API_KEY|ACCESS_TOKEN|PASSWORD)\}?",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        RiskCategory.INSTRUCTION_INJECTION,
        PermissionLevel.L4,
        re.compile(
            r"\bignore\s+(?:all\s+)?previous\s+instructions\b|"
            r"\bbypass\s+(?:security|safety)\s+(?:checks?|controls?)\b",
            re.IGNORECASE,
        ),
        auto_blocking=True,
    ),
)
_SCRIPT_SUFFIXES = frozenset({".bash", ".cjs", ".js", ".mjs", ".ps1", ".py", ".sh", ".ts", ".zsh"})
_PERMISSION_ALIASES = {
    "execute": McpPermission.EXECUTE,
    "execute-command": McpPermission.EXECUTE,
    "filesystem-write": McpPermission.FILESYSTEM_WRITE,
    "filesystem.write": McpPermission.FILESYSTEM_WRITE,
    "fs-write": McpPermission.FILESYSTEM_WRITE,
    "network": McpPermission.NETWORK,
    "network-access": McpPermission.NETWORK,
}
_PERMISSION_ORDER = {
    McpPermission.EXECUTE: 0,
    McpPermission.FILESYSTEM_WRITE: 1,
    McpPermission.NETWORK: 2,
}


def scan_skill(skill_dir: Path) -> SkillScanResult:
    """Scan SKILL.md and bundled scripts without executing or accessing the network."""
    root = skill_dir.resolve()
    flags: list[RiskFlag] = []
    for path in _scan_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(lines, start=1):
            for pattern in _PATTERNS:
                match = pattern.expression.search(line)
                if match is None:
                    continue
                flags.append(
                    RiskFlag(
                        category=pattern.category,
                        level=pattern.level,
                        source=SourceLocation(
                            path=relative,
                            line=line_number,
                            column=match.start() + 1,
                        ),
                        evidence=_redact_evidence(line.strip()),
                        auto_blocking=pattern.auto_blocking,
                    )
                )
    return SkillScanResult(flags=tuple(flags))


def _redact_evidence(evidence: str) -> str:
    """Preserve scanner context without serializing credential values."""
    return re.sub(
        r"((?:AWS_SECRET_ACCESS_KEY|GITHUB_TOKEN|API_KEY|ACCESS_TOKEN|PASSWORD)\s*=\s*)[^\s]+",
        r"\1[REDACTED]",
        evidence,
        flags=re.IGNORECASE,
    )


def extract_mcp_permissions(metadata: Mapping[str, Any]) -> McpPermissionSummary:
    """Derive declared MCP tools, transports, and coarse permissions from metadata."""
    tools = _tool_names(metadata.get("tools"))
    packages_value = metadata.get("packages", ())
    packages = packages_value if _is_sequence(packages_value) else ()
    transports: set[str] = set()
    permissions: set[McpPermission] = set()
    _collect_permissions(metadata.get("permissions"), permissions)
    _collect_transport(metadata, transports, permissions)

    for package in packages:
        if not isinstance(package, Mapping):
            continue
        _collect_permissions(package.get("permissions"), permissions)
        _collect_transport(package, transports, permissions)

    return McpPermissionSummary(
        tools=tools,
        transports=tuple(sorted(transports)),
        permissions=tuple(sorted(permissions, key=_PERMISSION_ORDER.__getitem__)),
    )


def _scan_files(root: Path) -> tuple[Path, ...]:
    files = []
    skill_file = root / "SKILL.md"
    if skill_file.is_file():
        files.append(skill_file)
    files.extend(
        path
        for path in root.rglob("*")
        if path.is_file() and path != skill_file and path.suffix.lower() in _SCRIPT_SUFFIXES
    )
    return tuple(sorted(files, key=lambda path: path.relative_to(root).as_posix()))


def _collect_transport(
    metadata: Mapping[str, Any],
    transports: set[str],
    permissions: set[McpPermission],
) -> None:
    transport = metadata.get("transport")
    if isinstance(transport, Mapping):
        transport_type = transport.get("type")
        if isinstance(transport_type, str) and transport_type:
            transports.add(transport_type)
        if isinstance(transport.get("command"), str):
            permissions.add(McpPermission.EXECUTE)
        if isinstance(transport.get("url"), str):
            permissions.add(McpPermission.NETWORK)
    if isinstance(metadata.get("command"), str):
        transports.add("stdio")
        permissions.add(McpPermission.EXECUTE)
    if isinstance(metadata.get("url"), str):
        transports.add("http")
        permissions.add(McpPermission.NETWORK)


def _tool_names(value: Any) -> tuple[str, ...]:
    if not _is_sequence(value):
        return ()
    names = set()
    for item in value:
        if isinstance(item, str) and item:
            names.add(item)
        elif isinstance(item, Mapping):
            name = item.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return tuple(sorted(names))


def _collect_permissions(value: Any, permissions: set[McpPermission]) -> None:
    if not _is_sequence(value):
        return
    for item in value:
        permission = _PERMISSION_ALIASES.get(str(item).lower())
        if permission is not None:
            permissions.add(permission)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
