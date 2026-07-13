"""Deterministic language, package-manager, framework, and workspace detection."""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vibe.models.repository import FactConfidence, RepositoryFact

_NODE_MANAGERS = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "pnpm-workspace.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lock": "bun",
    "bun.lockb": "bun",
}
_NODE_FRAMEWORKS = {
    "@angular/core": "angular",
    "next": "next",
    "react": "react",
    "svelte": "svelte",
    "vue": "vue",
}
_PYTHON_FRAMEWORKS = {"django", "fastapi", "flask"}
_RUST_FRAMEWORKS = {"actix-web", "axum", "rocket"}
_GO_FRAMEWORKS = {
    "github.com/gin-gonic/gin": "gin",
    "github.com/labstack/echo": "echo",
}


def inspect_stack(root: Path) -> tuple[RepositoryFact, ...]:
    """Return stable technology-stack facts rooted at *root*."""
    resolved = root.resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)

    languages: dict[str, set[str]] = {}
    managers: dict[str, set[str]] = {}
    frameworks: dict[str, set[str]] = {}
    workspaces: dict[str, set[str]] = {}
    node_managers: set[str] = set()
    inferred_node_manager = False

    package_json = _read_json(resolved / "package.json")
    if package_json is not None:
        _add(languages, "node", "package.json")
        manager_field = package_json.get("packageManager")
        if isinstance(manager_field, str):
            manager = manager_field.partition("@")[0].lower()
            if manager in {"npm", "pnpm", "yarn", "bun"}:
                _add(managers, manager, "package.json:packageManager")
                node_managers.add(manager)
        for filename, manager in _NODE_MANAGERS.items():
            if (resolved / filename).exists():
                _add(managers, manager, filename)
                node_managers.add(manager)
        if not node_managers:
            _add(managers, "npm", "package.json")
            inferred_node_manager = True
        for dependency in _json_dependencies(package_json):
            framework = _NODE_FRAMEWORKS.get(dependency)
            if framework is not None:
                _add(frameworks, framework, "package.json")
        if "workspaces" in package_json:
            _add(workspaces, "package.json:workspaces", "package.json")
        if (resolved / "pnpm-workspace.yaml").exists():
            _add(workspaces, "pnpm-workspace.yaml", "pnpm-workspace.yaml")

    pyproject = _read_toml(resolved / "pyproject.toml")
    if pyproject is not None:
        _add(languages, "python", "pyproject.toml")
        if (resolved / "uv.lock").exists():
            _add(managers, "uv", "uv.lock")
        for dependency in _python_dependencies(pyproject):
            if dependency in _PYTHON_FRAMEWORKS:
                _add(frameworks, dependency, "pyproject.toml")
        if _nested_mapping(pyproject, "tool", "uv", "workspace") is not None:
            _add(
                workspaces,
                "pyproject.toml:tool.uv.workspace",
                "pyproject.toml",
            )

    cargo = _read_toml(resolved / "Cargo.toml")
    if cargo is not None:
        _add(languages, "rust", "Cargo.toml")
        _add(managers, "cargo", "Cargo.toml")
        dependencies = cargo.get("dependencies")
        if isinstance(dependencies, Mapping):
            for dependency in dependencies:
                if dependency in _RUST_FRAMEWORKS:
                    _add(frameworks, str(dependency), "Cargo.toml")
        if isinstance(cargo.get("workspace"), Mapping):
            _add(workspaces, "Cargo.toml:workspace", "Cargo.toml")

    go_mod_path = resolved / "go.mod"
    if go_mod_path.is_file():
        go_mod = go_mod_path.read_text(encoding="utf-8", errors="replace")
        _add(languages, "go", "go.mod")
        _add(managers, "go", "go.mod")
        for module, framework in _GO_FRAMEWORKS.items():
            if module in go_mod:
                _add(frameworks, framework, "go.mod")
    if (resolved / "go.work").is_file():
        _add(workspaces, "go.work", "go.work")

    manager_confidence = FactConfidence.CONFIRMED
    if len(node_managers) > 1:
        manager_confidence = FactConfidence.CONFLICT
    elif inferred_node_manager and len(managers) == 1:
        manager_confidence = FactConfidence.INFERRED

    return (
        _fact("stack.languages", languages, FactConfidence.CONFIRMED),
        _fact("stack.package_managers", managers, manager_confidence),
        _fact("stack.frameworks", frameworks, FactConfidence.CONFIRMED),
        _fact("stack.workspaces", workspaces, FactConfidence.CONFIRMED),
    )


def _fact(
    key: str,
    values: dict[str, set[str]],
    confidence: FactConfidence,
) -> RepositoryFact:
    if not values:
        return RepositoryFact(key=key, value=None, confidence=FactConfidence.UNKNOWN)
    return RepositoryFact(
        key=key,
        value=sorted(values),
        confidence=confidence,
        sources=tuple(sorted({source for sources in values.values() for source in sources})),
    )


def _add(values: dict[str, set[str]], value: str, source: str) -> None:
    values.setdefault(value, set()).add(source)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path.name}: {exc.msg}") from exc
    return value if isinstance(value, dict) else None


def _read_toml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _json_dependencies(document: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for field in ("dependencies", "devDependencies"):
        dependencies = document.get(field)
        if isinstance(dependencies, Mapping):
            result.update(str(name).lower() for name in dependencies)
    return result


def _python_dependencies(document: Mapping[str, Any]) -> set[str]:
    project = document.get("project")
    if not isinstance(project, Mapping):
        return set()
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return set()
    return {
        re.split(r"[<>=!~;\[ ]", dependency, maxsplit=1)[0].lower()
        for dependency in dependencies
        if isinstance(dependency, str)
    }


def _nested_mapping(document: Mapping[str, Any], *keys: str) -> Mapping[str, Any] | None:
    current: Any = document
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, Mapping) else None
