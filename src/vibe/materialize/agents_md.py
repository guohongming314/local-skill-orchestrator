"""Safe byte-preserving merge support for generated AGENTS.md guidance."""

from __future__ import annotations

BEGIN_MARKER = b"<!-- local-skill-orchestrator:begin -->"
END_MARKER = b"<!-- local-skill-orchestrator:end -->"


class AgentsMdMergeError(ValueError):
    """Raised when managed block markers cannot be merged unambiguously."""


def merge_agents_md(existing: bytes | None, managed_content: str) -> bytes:
    """Create or replace one managed block while preserving all other bytes."""
    original = existing or b""
    newline = _newline_for(original)
    block = _managed_block(managed_content, newline)
    begins = _positions(original, BEGIN_MARKER)
    ends = _positions(original, END_MARKER)

    if not begins and not ends:
        if not original:
            return block
        separator = newline if original.endswith((b"\n", b"\r")) else newline + newline
        return original + separator + block

    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        raise AgentsMdMergeError(
            "AGENTS.md managed block markers are malformed or duplicated; "
            "keep exactly one ordered begin/end pair"
        )

    end_offset = ends[0] + len(END_MARKER)
    return original[: begins[0]] + block.rstrip(b"\r\n") + original[end_offset:]


def _managed_block(content: str, newline: bytes) -> bytes:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    body = normalized.encode("utf-8")
    if body:
        return (
            BEGIN_MARKER
            + newline
            + body.replace(b"\n", newline)
            + newline
            + END_MARKER
            + newline
        )
    return BEGIN_MARKER + newline + END_MARKER + newline


def _newline_for(content: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in content else b"\n"


def _positions(content: bytes, marker: bytes) -> tuple[int, ...]:
    positions: list[int] = []
    start = 0
    while True:
        position = content.find(marker, start)
        if position < 0:
            return tuple(positions)
        positions.append(position)
        start = position + len(marker)
