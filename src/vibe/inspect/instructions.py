"""Discovery of repository-local agent instruction files and their scopes."""

from __future__ import annotations

from pathlib import Path

from vibe.models.repository import FactConfidence, RepositoryFact

_INSTRUCTION_NAMES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules"}


def inspect_instructions(root: Path) -> tuple[RepositoryFact, ...]:
    """Find instruction files without interpreting their contents."""
    resolved = root.resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    discovered: dict[str, str] = {}
    for path in resolved.rglob("*"):
        if not path.is_file() or ".git" in path.relative_to(resolved).parts:
            continue
        relative = path.relative_to(resolved).as_posix()
        if path.name in _INSTRUCTION_NAMES:
            scope = path.parent.relative_to(resolved).as_posix()
            discovered[relative] = "." if scope == "." else scope
        elif ".cursor" in path.relative_to(resolved).parts and path.suffix == ".mdc":
            parts = path.relative_to(resolved).parts
            cursor_index = parts.index(".cursor")
            scope_path = Path(*parts[:cursor_index])
            scope = scope_path.as_posix()
            discovered[relative] = "." if scope == "." else scope
    if not discovered:
        return (
            RepositoryFact(
                key="instructions.files",
                value=None,
                confidence=FactConfidence.UNKNOWN,
            ),
        )
    paths = sorted(discovered)
    return (
        RepositoryFact(
            key="instructions.files",
            value=[f"{path} (scope: {discovered[path]})" for path in paths],
            confidence=FactConfidence.CONFIRMED,
            sources=tuple(paths),
        ),
    )
