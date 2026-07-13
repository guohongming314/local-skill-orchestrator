"""Static extraction of engineering commands from repository configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from vibe.models.repository import FactConfidence, RepositoryFact

_CATEGORIES = ("build", "format", "lint", "start", "test", "typecheck")
_SCRIPT_ALIASES = {
    "build": "build",
    "dev": "start",
    "fmt": "format",
    "format": "format",
    "lint": "lint",
    "start": "start",
    "test": "test",
    "type-check": "typecheck",
    "typecheck": "typecheck",
}
_MAKE_ALIASES = {**_SCRIPT_ALIASES, "check": "typecheck"}


def inspect_commands(root: Path) -> tuple[RepositoryFact, ...]:
    """Extract commands and provenance without invoking a shell."""
    resolved = root.resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    commands: dict[str, dict[str, set[str]]] = {category: {} for category in _CATEGORIES}

    package_path = resolved / "package.json"
    if package_path.is_file():
        package: Any = json.loads(package_path.read_text(encoding="utf-8"))
        if isinstance(package, dict):
            scripts = package.get("scripts")
            if isinstance(scripts, dict):
                for name, command in scripts.items():
                    category = _SCRIPT_ALIASES.get(str(name))
                    if category is not None and isinstance(command, str):
                        _add(
                            commands[category],
                            command,
                            f"package.json:scripts.{name}",
                        )

    makefile = resolved / "Makefile"
    if makefile.is_file():
        for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", line)
            if match is None:
                continue
            target = match.group(1)
            category = _MAKE_ALIASES.get(target)
            if category is not None:
                _add(commands[category], f"make {target}", f"Makefile:{target}")

    return tuple(_command_fact(category, commands[category]) for category in _CATEGORIES)


def _command_fact(category: str, values: dict[str, set[str]]) -> RepositoryFact:
    if not values:
        return RepositoryFact(
            key=f"commands.{category}",
            value=None,
            confidence=FactConfidence.UNKNOWN,
        )
    return RepositoryFact(
        key=f"commands.{category}",
        value=sorted(values),
        confidence=(
            FactConfidence.CONFIRMED if len(values) == 1 else FactConfidence.CONFLICT
        ),
        sources=tuple(sorted({source for sources in values.values() for source in sources})),
    )


def _add(values: dict[str, set[str]], command: str, source: str) -> None:
    values.setdefault(command, set()).add(source)
