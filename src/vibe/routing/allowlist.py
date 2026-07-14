"""Fail-closed loading of capsule-selected MCP tool names."""

from __future__ import annotations

import json
from pathlib import Path


class AllowlistError(ValueError):
    """Raised when a capsule selection file is missing or invalid."""


class AllowlistFile:
    """Read an exact tool allowlist from disk on every policy decision.

    Reading at the decision boundary makes file replacement hot-reload immediately while
    ensuring malformed or missing selections fail closed.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def tools(self) -> tuple[str, ...]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise AllowlistError(f"cannot load allowlist: {type(error).__name__}") from error

        if not isinstance(payload, dict):
            raise AllowlistError("allowlist must be a JSON object")
        allowed_tools = payload.get("allowed_tools")
        if not isinstance(allowed_tools, list) or not all(
            isinstance(item, str) and item for item in allowed_tools
        ):
            raise AllowlistError("allowed_tools must be a list of non-empty strings")
        if len(allowed_tools) != len(set(allowed_tools)):
            raise AllowlistError("allowed_tools must not contain duplicates")
        return tuple(allowed_tools)
