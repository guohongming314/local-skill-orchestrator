"""Static discovery of repository infrastructure with file provenance."""

from __future__ import annotations

from pathlib import Path

from vibe.models.repository import FactConfidence, RepositoryFact

_DATABASE_MARKERS = {
    "cockroachdb": "cockroachdb",
    "mariadb": "mariadb",
    "mongodb": "mongodb",
    "mysql": "mysql",
    "postgres": "postgresql",
    "redis": "redis",
    "sqlite": "sqlite",
}
_MIGRATION_PATHS = (
    "migrations",
    "alembic/versions",
    "db/migrations",
    "prisma/migrations",
)


def inspect_infrastructure(root: Path) -> tuple[RepositoryFact, ...]:
    """Discover infrastructure declarations without running project tooling."""
    resolved = root.resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)

    workflows = _relative_files(resolved, ".github/workflows", ("*.yml", "*.yaml"))
    docker = _docker_files(resolved)
    devcontainers = _relative_files(resolved, ".devcontainer", ("*.json", "Dockerfile*"))
    databases: dict[str, set[str]] = {}
    for relative in docker:
        path = resolved / relative
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for marker, database in _DATABASE_MARKERS.items():
            if marker in text:
                databases.setdefault(database, set()).add(relative)
    migrations = [
        relative
        for relative in _MIGRATION_PATHS
        if (resolved / relative).is_dir()
    ]

    return (
        _path_fact("infrastructure.github_actions", workflows),
        _path_fact("infrastructure.docker", docker),
        _path_fact("infrastructure.devcontainers", devcontainers),
        _value_fact("infrastructure.databases", databases),
        _path_fact("infrastructure.migrations", migrations),
    )


def _relative_files(root: Path, directory: str, patterns: tuple[str, ...]) -> list[str]:
    base = root / directory
    if not base.is_dir():
        return []
    paths = {
        path.relative_to(root).as_posix()
        for pattern in patterns
        for path in base.rglob(pattern)
        if path.is_file()
    }
    return sorted(paths)


def _docker_files(root: Path) -> list[str]:
    paths = {
        path.relative_to(root).as_posix()
        for pattern in (
            "Dockerfile*",
            "compose*.yml",
            "compose*.yaml",
            "docker-compose*.yml",
            "docker-compose*.yaml",
        )
        for path in root.glob(pattern)
        if path.is_file()
    }
    return sorted(paths)


def _path_fact(key: str, paths: list[str]) -> RepositoryFact:
    if not paths:
        return RepositoryFact(key=key, value=None, confidence=FactConfidence.UNKNOWN)
    return RepositoryFact(
        key=key,
        value=paths,
        confidence=FactConfidence.CONFIRMED,
        sources=tuple(paths),
    )


def _value_fact(key: str, values: dict[str, set[str]]) -> RepositoryFact:
    if not values:
        return RepositoryFact(key=key, value=None, confidence=FactConfidence.UNKNOWN)
    return RepositoryFact(
        key=key,
        value=sorted(values),
        confidence=FactConfidence.CONFIRMED,
        sources=tuple(sorted({source for sources in values.values() for source in sources})),
    )
