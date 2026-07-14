from pathlib import Path

from vibe.commands.init import _repository_with_project_type
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot


def snapshot(*facts: RepositoryFact) -> RepositorySnapshot:
    return RepositorySnapshot(
        root=Path("project"),
        is_empty=not facts,
        facts=facts,
        source_digest="a" * 64,
    )


def project_type(repository: RepositorySnapshot) -> RepositoryFact:
    return next(fact for fact in repository.facts if fact.key == "project_type")


def test_interview_answer_becomes_confirmed_project_type_fact() -> None:
    repository = _repository_with_project_type(
        snapshot(), {"project_type": "web-application"}
    )

    fact = project_type(repository)
    assert fact.value == "web-application"
    assert fact.confidence is FactConfidence.CONFIRMED
    assert fact.sources == ("interview:project.type",)


def test_inferred_project_type_is_preserved_without_interview_answer() -> None:
    inferred = RepositoryFact(
        key="project_type",
        value="backend-api",
        confidence=FactConfidence.INFERRED,
        sources=("pyproject.toml",),
    )

    repository = _repository_with_project_type(snapshot(inferred), {})

    assert project_type(repository) == inferred
