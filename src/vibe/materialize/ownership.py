from __future__ import annotations

from enum import StrEnum


class FileOwnership(StrEnum):
    """How the orchestrator may interact with a project file."""

    OWNED = "owned"
    MANAGED = "managed"
    OBSERVED = "observed"


class OwnershipViolation(ValueError):
    """Raised when a proposed mutation exceeds its declared ownership."""
