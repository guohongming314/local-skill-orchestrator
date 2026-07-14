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
_WEB_FRAMEWORKS = {"angular", "django", "next", "react", "svelte", "vue"}
_API_FRAMEWORKS = {"actix-web", "axum", "fastapi", "flask", "gin", "echo", "rocket"}
_AI_DEPENDENCIES = {
    "anthropic",
    "langchain",
    "llama-index",
    "openai",
    "tensorflow",
    "torch",
    "transformers",
}
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
    project_types: dict[str, set[str]] = {}
    packaging_sources: set[str] = set()
    node_managers: set[str] = set()
    inferred_node_manager = False

    package_json = _read_json(resolved / "package.json")
    if package_json is not None:
        packaging_sources.add("package.json")
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
        node_dependencies = _json_dependencies(package_json)
        for dependency in node_dependencies:
            framework = _NODE_FRAMEWORKS.get(dependency)
            if framework is not None:
                _add(frameworks, framework, "package.json")
        if node_dependencies & _AI_DEPENDENCIES:
            _add(project_types, "ai-application", "package.json")
        if isinstance(package_json.get("bin"), (str, Mapping)):
            _add(project_types, "cli-tool", "package.json:bin")
        if "workspaces" in package_json:
            _add(workspaces, "package.json:workspaces", "package.json")
        if (resolved / "pnpm-workspace.yaml").exists():
            _add(workspaces, "pnpm-workspace.yaml", "pnpm-workspace.yaml")

    pyproject = _read_toml(resolved / "pyproject.toml")
    if pyproject is not None:
        packaging_sources.add("pyproject.toml")
        _add(languages, "python", "pyproject.toml")
        if (resolved / "uv.lock").exists():
            _add(managers, "uv", "uv.lock")
        python_dependencies = _python_dependencies(pyproject)
        for dependency in python_dependencies:
            if dependency in _PYTHON_FRAMEWORKS:
                _add(frameworks, dependency, "pyproject.toml")
        if python_dependencies & _AI_DEPENDENCIES:
            _add(project_types, "ai-application", "pyproject.toml")
        if _nested_mapping(pyproject, "project", "scripts") is not None:
            _add(project_types, "cli-tool", "pyproject.toml:project.scripts")
        if _nested_mapping(pyproject, "tool", "uv", "workspace") is not None:
            _add(
                workspaces,
                "pyproject.toml:tool.uv.workspace",
                "pyproject.toml",
            )

    cargo = _read_toml(resolved / "Cargo.toml")
    if cargo is not None:
        packaging_sources.add("Cargo.toml")
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
        packaging_sources.add("go.mod")
        go_mod = go_mod_path.read_text(encoding="utf-8", errors="replace")
        _add(languages, "go", "go.mod")
        _add(managers, "go", "go.mod")
        for module, framework in _GO_FRAMEWORKS.items():
            if module in go_mod:
                _add(frameworks, framework, "go.mod")
    if (resolved / "go.work").is_file():
        _add(workspaces, "go.work", "go.work")

    for framework, sources in frameworks.items():
        if framework in _WEB_FRAMEWORKS:
            project_types.setdefault("web-application", set()).update(sources)
        if framework in _API_FRAMEWORKS:
            project_types.setdefault("backend-api", set()).update(sources)
    if not project_types and packaging_sources:
        project_types["open-source-library"] = packaging_sources

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
        _project_type_fact(project_types),
    )


def _project_type_fact(values: dict[str, set[str]]) -> RepositoryFact:
    if not values:
        return RepositoryFact(
            key="project_type", value=None, confidence=FactConfidence.UNKNOWN
        )
    ordered = sorted(values)
    return RepositoryFact(
        key="project_type",
        value=ordered[0] if len(ordered) == 1 else ordered,
        confidence=(
            FactConfidence.INFERRED if len(ordered) == 1 else FactConfidence.CONFLICT
        ),
        sources=tuple(sorted({source for sources in values.values() for source in sources})),
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
