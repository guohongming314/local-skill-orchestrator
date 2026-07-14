from __future__ import annotations

from pathlib import Path

import pytest

from vibe.inspect.stack import inspect_stack
from vibe.models.repository import FactConfidence, RepositoryFact

FIXTURES = Path(__file__).parents[1] / "fixtures" / "repositories"


def facts(name: str) -> dict[str, RepositoryFact]:
    return {fact.key: fact for fact in inspect_stack(FIXTURES / name)}


@pytest.mark.parametrize(
    ("fixture", "language", "manager", "framework", "workspace"),
    [
        ("node-pnpm", "node", "pnpm", "next", "package.json:workspaces"),
        ("python-uv", "python", "uv", "fastapi", "pyproject.toml:tool.uv.workspace"),
        ("rust", "rust", "cargo", "axum", "Cargo.toml:workspace"),
        ("go", "go", "go", "gin", None),
    ],
)
def test_supported_single_stack_fixtures_are_confirmed(
    fixture: str,
    language: str,
    manager: str,
    framework: str,
    workspace: str | None,
) -> None:
    result = facts(fixture)

    assert result["stack.languages"].value == [language]
    assert result["stack.languages"].confidence is FactConfidence.CONFIRMED
    assert result["stack.package_managers"].value == [manager]
    assert result["stack.package_managers"].confidence is FactConfidence.CONFIRMED
    framework_value = result["stack.frameworks"].value
    assert isinstance(framework_value, list)
    assert framework in framework_value
    assert result["stack.frameworks"].confidence is FactConfidence.CONFIRMED
    if workspace is not None:
        workspace_value = result["stack.workspaces"].value
        assert isinstance(workspace_value, list)
        assert workspace in workspace_value
        assert result["stack.workspaces"].confidence is FactConfidence.CONFIRMED


def test_competing_node_package_managers_emit_conflict_with_sources() -> None:
    manager = facts("node-conflict")["stack.package_managers"]

    assert manager.value == ["npm", "yarn"]
    assert manager.confidence is FactConfidence.CONFLICT
    assert manager.sources == ("package-lock.json", "yarn.lock")


def test_manifest_without_manager_signal_is_inferred() -> None:
    manager = facts("node-inferred")["stack.package_managers"]

    assert manager.value == ["npm"]
    assert manager.confidence is FactConfidence.INFERRED
    assert manager.sources == ("package.json",)


def test_unsupported_stack_remains_unknown() -> None:
    result = facts("unsupported")

    for key in (
        "stack.languages",
        "stack.package_managers",
        "stack.frameworks",
        "stack.workspaces",
    ):
        assert result[key].value is None
        assert result[key].confidence is FactConfidence.UNKNOWN


@pytest.mark.parametrize(
    ("signal", "manager"),
    [
        ("package-lock.json", "npm"),
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lock", "bun"),
    ],
)
def test_node_lockfiles_confirm_each_supported_manager(
    tmp_path: Path, signal: str, manager: str
) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / signal).write_text("", encoding="utf-8")

    fact = {fact.key: fact for fact in inspect_stack(tmp_path)}[
        "stack.package_managers"
    ]

    assert fact.value == [manager]
    assert fact.confidence is FactConfidence.CONFIRMED
    assert fact.sources == (signal,)


@pytest.mark.parametrize(
    ("fixture", "project_type"),
    [
        ("node-pnpm", "web-application"),
        ("python-uv", "backend-api"),
        ("rust", "backend-api"),
        ("go", "backend-api"),
        ("node-inferred", "open-source-library"),
    ],
)
def test_stack_fixtures_infer_project_type(
    fixture: str, project_type: str
) -> None:
    fact = facts(fixture)["project_type"]

    assert fact.value == project_type
    assert fact.confidence is FactConfidence.INFERRED


def test_console_entry_point_infers_cli_project_type(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "tool"\n[project.scripts]\ntool = "tool:main"\n',
        encoding="utf-8",
    )

    fact = {item.key: item for item in inspect_stack(tmp_path)}["project_type"]

    assert fact.value == "cli-tool"
    assert fact.confidence is FactConfidence.INFERRED
    assert fact.sources == ("pyproject.toml:project.scripts",)


def test_ml_dependency_infers_ai_application(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "assistant"\ndependencies = ["langchain>=1"]\n',
        encoding="utf-8",
    )

    fact = {item.key: item for item in inspect_stack(tmp_path)}["project_type"]

    assert fact.value == "ai-application"
    assert fact.confidence is FactConfidence.INFERRED
