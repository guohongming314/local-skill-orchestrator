from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from vibe.materialize.changeset import (
    ChangeKind,
    ChangeProposal,
    Sensitivity,
    build_changeset,
    render_dry_run,
)
from vibe.materialize.ownership import FileOwnership, OwnershipViolation


def proposal(
    path: str,
    content: str | None,
    ownership: FileOwnership,
    *,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
) -> ChangeProposal:
    return ChangeProposal(
        path=path,
        desired_content=content,
        ownership=ownership,
        source="acceptance:fixture",
        reason=f"Manage {path}",
        sensitivity=sensitivity,
    )


def test_repeated_generation_is_stable_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("before", encoding="utf-8")
    proposals = (
        proposal("z-created.txt", "new", FileOwnership.OWNED),
        proposal("existing.txt", "after", FileOwnership.MANAGED),
    )

    first = build_changeset(tmp_path, proposals)
    second = build_changeset(tmp_path, tuple(reversed(proposals)))

    assert first == second
    assert first.digest == second.digest
    assert [operation.path for operation in first.operations] == [
        "existing.txt",
        "z-created.txt",
    ]


def test_create_update_delete_and_unchanged_are_modeled(tmp_path: Path) -> None:
    (tmp_path / "update.txt").write_text("before", encoding="utf-8")
    (tmp_path / "delete.txt").write_text("remove", encoding="utf-8")
    (tmp_path / "same.txt").write_text("same", encoding="utf-8")

    changeset = build_changeset(
        tmp_path,
        (
            proposal("create.txt", "created", FileOwnership.OWNED),
            proposal("update.txt", "after", FileOwnership.MANAGED),
            proposal("delete.txt", None, FileOwnership.OWNED),
            proposal("same.txt", "same", FileOwnership.MANAGED),
        ),
    )

    assert {item.path: item.kind for item in changeset.operations} == {
        "create.txt": ChangeKind.CREATE,
        "delete.txt": ChangeKind.DELETE,
        "same.txt": ChangeKind.UNCHANGED,
        "update.txt": ChangeKind.UPDATE,
    }


def test_existing_observed_files_never_receive_write_operations(tmp_path: Path) -> None:
    path = tmp_path / "user-owned.txt"
    path.write_text("user content", encoding="utf-8")

    changeset = build_changeset(
        tmp_path,
        (proposal("user-owned.txt", "generated content", FileOwnership.OBSERVED),),
    )

    operation = changeset.operations[0]
    assert operation.kind is ChangeKind.UNCHANGED
    assert operation.before_content == "user content"
    assert operation.after_content == "user content"
    assert path.read_text(encoding="utf-8") == "user content"


def test_owned_deletes_are_allowed_but_managed_deletes_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "managed.txt").write_text("managed", encoding="utf-8")

    with pytest.raises(OwnershipViolation, match="managed files cannot be deleted"):
        build_changeset(
            tmp_path,
            (proposal("managed.txt", None, FileOwnership.MANAGED),),
        )


def test_every_operation_has_source_reason_and_before_after_digests(tmp_path: Path) -> None:
    changeset = build_changeset(
        tmp_path,
        (proposal("created.txt", "content", FileOwnership.OWNED),),
    )

    operation = changeset.operations[0]
    assert operation.source == "acceptance:fixture"
    assert operation.reason == "Manage created.txt"
    assert len(operation.before_digest) == 64
    assert len(operation.after_digest) == 64
    assert operation.after_digest == hashlib.sha256(b"content").hexdigest()


def test_human_readable_dry_run_is_stable_and_redacts_sensitive_content(
    tmp_path: Path,
) -> None:
    secret = "SUPER-SECRET-GENERATED-VALUE"
    changeset = build_changeset(
        tmp_path,
        (
            proposal(
                ".vibe/secret.toml",
                secret,
                FileOwnership.OWNED,
                sensitivity=Sensitivity.SENSITIVE,
            ),
        ),
    )

    rendered = render_dry_run(changeset)

    assert "CREATE .vibe/secret.toml" in rendered
    assert "owned" in rendered
    assert "sensitive" in rendered
    assert "acceptance:fixture" in rendered
    assert secret not in rendered
