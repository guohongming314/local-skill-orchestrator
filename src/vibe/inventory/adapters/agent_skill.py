"""Read-only adapter for project and user Agent Skills."""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from vibe.inventory.adapters.base import (
    AdapterDiscovery,
    AdapterProvenance,
    AdapterScanError,
    AdapterScanResult,
    AdapterVerification,
)
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)

_FRONTMATTER = re.compile(r"\A---\s*\r?\n(?P<header>.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)
_MARKDOWN_LINK = re.compile(r"\[[^]]*]\((?P<target>[^)]+)\)")
_SECRET_PARTS = re.compile(
    r"(?:^|[._-])(secret|credential|credentials|token|password|passwd|private|id_rsa)(?:$|[._-])",
    re.IGNORECASE,
)
_SECRET_SUFFIXES = frozenset({".key", ".pem", ".p12", ".pfx"})


@dataclass(frozen=True)
class SkillRoot:
    """A directory containing Skills with one declared capability scope."""

    path: Path
    scope: CapabilityScope


class AgentSkillAdapter:
    """Discover and safely normalize Agent Skills without executing them."""

    adapter_id = "agent-skill"

    def __init__(self, *, roots: tuple[SkillRoot, ...]) -> None:
        self._roots = tuple(sorted(roots, key=lambda item: (item.scope.value, str(item.path))))

    def discover(self) -> tuple[AdapterDiscovery, ...]:
        discoveries: list[AdapterDiscovery] = []
        for root in self._roots:
            if not root.path.is_dir():
                continue
            discoveries.extend(
                AdapterDiscovery(locator=str(skill_file.resolve()))
                for skill_file in root.path.glob("*/SKILL.md")
                if skill_file.is_file()
            )
        return tuple(sorted(discoveries, key=lambda item: item.locator))

    def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
        skill_file = Path(discovery.locator).resolve()
        root = self._root_for(skill_file)
        try:
            text = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise AdapterScanError(f"cannot read SKILL.md: {error}") from error

        metadata, body = _parse_frontmatter(text)
        name = _required(metadata, "name")
        description = _required(metadata, "description")
        skill_directory = skill_file.parent
        details: list[str] = []
        if skill_directory.name != name:
            details.append(f"directory_name_mismatch:{skill_directory.name}!={name}")

        required_tools = _words(metadata.get("required-tools", ""))
        for tool in required_tools:
            if shutil.which(tool) is None:
                details.append(f"missing_tool:{tool}")

        digest = hashlib.sha256()
        digest.update(b"SKILL.md\0")
        digest.update(text.encode())
        for dependency in _local_dependencies(body):
            normalized = dependency.as_posix()
            candidate = (skill_directory / dependency).resolve()
            if _secret_like(dependency):
                details.append(f"secret_dependency_skipped:{normalized}")
                continue
            if not candidate.is_relative_to(skill_directory):
                details.append(f"unsafe_dependency_skipped:{normalized}")
                continue
            if not candidate.is_file():
                details.append(f"missing_dependency:{normalized}")
                continue
            try:
                content = candidate.read_bytes()
            except OSError as error:
                details.append(f"unreadable_dependency:{normalized}:{type(error).__name__}")
                continue
            digest.update(normalized.encode())
            digest.update(b"\0")
            digest.update(content)
            details.append(f"dependency:{normalized}")

        permissions = _permissions(metadata.get("allowed-tools", ""))
        problems = tuple(
            sorted(detail for detail in details if not detail.startswith("dependency:"))
        )
        verified = not problems
        verification_details = tuple(sorted(details))
        manifest = CapabilityManifest(
            capability_id=f"skill.{name}",
            name=name,
            kind=CapabilityKind.SKILL,
            scope=root.scope,
            source=str(skill_file),
            provides=(description,),
            permissions=permissions,
            version=metadata.get("version"),
            content_digest=digest.hexdigest(),
            verified=verified,
        )
        return AdapterScanResult(
            manifest=manifest,
            provenance=AdapterProvenance(adapter_id=self.adapter_id, locator=str(skill_file)),
            verification=AdapterVerification(
                verified=verified,
                details=verification_details,
            ),
        )

    def _root_for(self, skill_file: Path) -> SkillRoot:
        for root in self._roots:
            resolved_root = root.path.resolve()
            direct_child = skill_file.parent.parent == resolved_root
            if skill_file.is_relative_to(resolved_root) and direct_child:
                return root
        raise AdapterScanError(f"locator is outside configured roots: {skill_file}")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER.match(text)
    if match is None:
        raise AdapterScanError("SKILL.md frontmatter is missing or malformed")
    metadata: dict[str, str] = {}
    for line_number, line in enumerate(match.group("header").splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() or ":" not in line:
            raise AdapterScanError(f"unsupported frontmatter entry on line {line_number}")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise AdapterScanError(f"empty frontmatter key on line {line_number}")
        metadata[key] = _unquote(value.strip())
    return metadata, text[match.end() :]


def _required(metadata: dict[str, str], key: str) -> str:
    value = metadata.get(key, "").strip()
    if not value:
        raise AdapterScanError(f"required frontmatter field {key!r} is missing")
    return value


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _words(value: str) -> tuple[str, ...]:
    return tuple(sorted({item for item in re.split(r"[\s,]+", value) if item}))


def _permissions(allowed_tools: str) -> frozenset[Permission]:
    permissions: set[Permission] = set()
    tools = {item.split("(", 1)[0].lower() for item in _words(allowed_tools)}
    if tools & {"read", "grep", "glob"}:
        permissions.add(Permission.READ_PROJECT)
    if tools & {"write", "edit"}:
        permissions.add(Permission.WRITE_PROJECT)
    if tools & {"bash", "shell", "powershell", "cmd"}:
        permissions.add(Permission.EXECUTE_COMMAND)
    if tools & {"webfetch", "websearch", "network"}:
        permissions.add(Permission.NETWORK)
    return frozenset(permissions)


def _local_dependencies(body: str) -> tuple[Path, ...]:
    dependencies: set[Path] = set()
    for match in _MARKDOWN_LINK.finditer(body):
        target = match.group("target").split("#", 1)[0].strip()
        if not target or "://" in target or target.startswith(("#", "mailto:")):
            continue
        dependencies.add(Path(*target.replace("\\", "/").split("/")))
    return tuple(sorted(dependencies, key=lambda item: item.as_posix()))


def _secret_like(path: Path) -> bool:
    return any(
        part.lower() == ".env"
        or _SECRET_PARTS.search(part) is not None
        or Path(part).suffix.lower() in _SECRET_SUFFIXES
        for part in path.parts
    )

