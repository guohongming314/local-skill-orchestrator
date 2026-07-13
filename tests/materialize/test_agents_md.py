from __future__ import annotations

import pytest

from vibe.materialize.agents_md import AgentsMdMergeError, merge_agents_md

BEGIN = b"<!-- local-skill-orchestrator:begin -->"
END = b"<!-- local-skill-orchestrator:end -->"


def test_creates_missing_agents_md_with_managed_block() -> None:
    result = merge_agents_md(None, "Use project quality gates.\n")

    assert result == (
        BEGIN
        + b"\nUse project quality gates.\n"
        + END
        + b"\n"
    )


def test_preserves_existing_bytes_outside_managed_block() -> None:
    existing = b"# User instructions\r\n\r\nKeep this exactly.\r\n"

    result = merge_agents_md(existing, "Generated guidance.\n")

    assert result.startswith(existing)
    assert result == existing + b"\r\n" + BEGIN + b"\r\nGenerated guidance.\r\n" + END + b"\r\n"


def test_updates_only_managed_block_and_is_idempotent() -> None:
    before = b"prefix\n" + BEGIN + b"\nold\n" + END + b"\nsuffix\n"

    updated = merge_agents_md(before, "new\n")

    assert updated == b"prefix\n" + BEGIN + b"\nnew\n" + END + b"\nsuffix\n"
    assert merge_agents_md(updated, "new\n") == updated


@pytest.mark.parametrize(
    "existing",
    [
        BEGIN + b"\nmissing end\n",
        END + b"\nmissing begin\n",
        BEGIN + b"\na\n" + END + b"\n" + BEGIN + b"\nb\n" + END,
        END + b"\n" + BEGIN,
    ],
)
def test_refuses_malformed_or_duplicated_markers(existing: bytes) -> None:
    with pytest.raises(AgentsMdMergeError, match="managed block markers"):
        merge_agents_md(existing, "replacement\n")


def test_refuses_non_utf8_managed_content_but_preserves_arbitrary_user_bytes() -> None:
    existing = b"user:\xff\n"

    result = merge_agents_md(existing, "safe\n")

    assert result.startswith(existing)
