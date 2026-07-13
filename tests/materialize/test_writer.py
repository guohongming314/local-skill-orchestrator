from __future__ import annotations

import os
from pathlib import Path

import pytest

from vibe.materialize.changeset import ChangeProposal, build_changeset
from vibe.materialize.ownership import FileOwnership
from vibe.materialize.writer import ApplyFailure, ConcurrentChangeError, apply_changeset


def proposal(path: str, content: str | None) -> ChangeProposal:
    return ChangeProposal(
        path=path,
        desired_content=content,
        ownership=FileOwnership.OWNED,
        source="test",
        reason="verify atomic writer",
    )


def test_concurrent_change_aborts_before_any_mutation(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("before", encoding="utf-8")
    changeset = build_changeset(
        tmp_path,
        (proposal("existing.txt", "after"), proposal("created.txt", "created")),
    )
    (tmp_path / "existing.txt").write_text("concurrent", encoding="utf-8")

    with pytest.raises(ConcurrentChangeError, match=r"existing\.txt"):
        apply_changeset(changeset)

    assert (tmp_path / "existing.txt").read_text(encoding="utf-8") == "concurrent"
    assert not (tmp_path / "created.txt").exists()


def test_injected_write_failure_restores_original_tree(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a-before", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b-before", encoding="utf-8")
    changeset = build_changeset(
        tmp_path,
        (proposal("a.txt", "a-after"), proposal("b.txt", "b-after")),
    )
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected failure")
        os.replace(source, target)

    with pytest.raises(ApplyFailure, match="rolled back"):
        apply_changeset(changeset, replace=fail_second)

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a-before"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "b-before"
    assert not any(path.name.startswith(".vibe-") for path in tmp_path.iterdir())


def test_apply_creates_updates_deletes_and_repeated_plan_is_unchanged(tmp_path: Path) -> None:
    (tmp_path / "update.txt").write_text("before", encoding="utf-8")
    (tmp_path / "delete.txt").write_text("remove", encoding="utf-8")
    proposals = (
        proposal("create/nested.txt", "created"),
        proposal("delete.txt", None),
        proposal("update.txt", "after"),
    )

    result = apply_changeset(build_changeset(tmp_path, proposals))

    assert result.applied_paths == ("create/nested.txt", "delete.txt", "update.txt")
    assert (tmp_path / "create/nested.txt").read_text(encoding="utf-8") == "created"
    assert not (tmp_path / "delete.txt").exists()
    assert (tmp_path / "update.txt").read_text(encoding="utf-8") == "after"
    repeated = build_changeset(tmp_path, proposals)
    assert all(operation.kind.value == "unchanged" for operation in repeated.operations)
    assert apply_changeset(repeated).applied_paths == ()


