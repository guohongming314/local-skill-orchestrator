from enum import StrEnum
from pathlib import Path

from pydantic import Field

from vibe.models.base import VersionedModel


class FactConfidence(StrEnum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


class RepositoryFact(VersionedModel):
    key: str = Field(min_length=1)
    value: str | list[str] | None
    confidence: FactConfidence
    sources: tuple[str, ...] = ()


class RepositorySnapshot(VersionedModel):
    root: Path
    is_empty: bool
    git_root: Path | None = None
    head: str | None = None
    dirty: bool | None = None
    facts: tuple[RepositoryFact, ...] = ()
    source_digest: str = Field(min_length=8)

