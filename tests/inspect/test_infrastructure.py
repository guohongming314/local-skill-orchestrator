from __future__ import annotations

from pathlib import Path

from vibe.inspect.infrastructure import inspect_infrastructure
from vibe.models.repository import FactConfidence, RepositoryFact


def facts(root: Path) -> dict[str, RepositoryFact]:
    return {fact.key: fact for fact in inspect_infrastructure(root)}


def test_infrastructure_facts_cite_source_files(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    devcontainer = tmp_path / ".devcontainer" / "devcontainer.json"
    devcontainer.parent.mkdir()
    devcontainer.write_text("{}\n", encoding="utf-8")
    (tmp_path / "compose.yaml").write_text(
        "services:\n  db:\n    image: postgres:17\n", encoding="utf-8"
    )
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001.sql").write_text("select 1;\n", encoding="utf-8")

    result = facts(tmp_path)

    assert result["infrastructure.github_actions"].value == [
        ".github/workflows/ci.yml"
    ]
    assert result["infrastructure.docker"].value == ["Dockerfile", "compose.yaml"]
    assert result["infrastructure.devcontainers"].value == [
        ".devcontainer/devcontainer.json"
    ]
    assert result["infrastructure.databases"].value == ["postgresql"]
    assert result["infrastructure.databases"].sources == ("compose.yaml",)
    assert result["infrastructure.migrations"].value == ["migrations"]
    assert result["infrastructure.migrations"].sources == ("migrations",)
    assert all(fact.confidence is FactConfidence.CONFIRMED for fact in result.values())


def test_absent_infrastructure_is_unknown(tmp_path: Path) -> None:
    result = facts(tmp_path)

    assert all(fact.value is None for fact in result.values())
    assert all(fact.confidence is FactConfidence.UNKNOWN for fact in result.values())
