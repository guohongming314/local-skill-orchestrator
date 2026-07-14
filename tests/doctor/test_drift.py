from __future__ import annotations

from pathlib import Path

from vibe.compiler.invalidation import InvalidationKind
from vibe.doctor.drift import detect_drift
from vibe.materialize.changeset import ChangeProposal, ChangeSet, build_changeset
from vibe.materialize.ownership import FileOwnership
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot


def snapshot(
    root: Path,
    *,
    head: str = "head-a",
    source_digest: str = "source-a",
    stack: tuple[RepositoryFact, ...] = (),
) -> RepositorySnapshot:
    return RepositorySnapshot(
        root=root,
        is_empty=False,
        git_root=root,
        head=head,
        dirty=False,
        facts=stack,
        source_digest=source_digest,
    )


def stack_fact(*values: str, source: str = "pyproject.toml") -> RepositoryFact:
    return RepositoryFact(
        key="stack.frameworks",
        value=list(values),
        confidence=FactConfidence.CONFIRMED,
        sources=(source,),
    )


def proposed_change(
    root: Path,
    path: str,
    *,
    ownership: FileOwnership = FileOwnership.OWNED,
) -> ChangeSet:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("before\n", encoding="utf-8")
    return build_changeset(
        root,
        (
            ChangeProposal(
                path=path,
                desired_content="after\n",
                ownership=ownership,
                source="regenerated project configuration",
                reason="configuration differs",
            ),
        ),
    )


def test_git_head_and_unrelated_source_changes_are_distinct_but_noninvalidating(
    tmp_path: Path,
) -> None:
    baseline = snapshot(tmp_path)
    current = snapshot(tmp_path, head="head-b", source_digest="source-b")

    report = detect_drift(baseline, current, build_changeset(tmp_path, ()))

    assert tuple(reason.kind for reason in report.reasons) == (
        InvalidationKind.GIT_HEAD_CHANGED,
        InvalidationKind.REPOSITORY_SOURCE_CHANGED,
    )
    assert not report.invalidates_configuration
    assert report.reasons[0].sources == ("git HEAD",)


def test_technology_stack_change_invalidates_and_cites_changed_sources(
    tmp_path: Path,
) -> None:
    baseline = snapshot(tmp_path, stack=(stack_fact("flask"),))
    current = snapshot(
        tmp_path,
        source_digest="source-b",
        stack=(stack_fact("fastapi", source="pyproject.toml:project.dependencies"),),
    )

    report = detect_drift(baseline, current, build_changeset(tmp_path, ()))

    reason = next(
        item for item in report.reasons if item.kind is InvalidationKind.TECHNOLOGY_STACK_CHANGED
    )
    assert reason.invalidates_configuration
    assert reason.sources == ("pyproject.toml", "pyproject.toml:project.dependencies")
    assert report.invalidates_configuration


def test_lockfile_and_other_managed_file_drift_are_distinguishable(
    tmp_path: Path,
) -> None:
    baseline = snapshot(tmp_path)

    lock_report = detect_drift(
        baseline,
        baseline,
        proposed_change(tmp_path, ".ai-project/capabilities.lock"),
    )
    managed_report = detect_drift(
        baseline,
        baseline,
        proposed_change(tmp_path, ".ai-project/policy.yaml"),
    )

    assert lock_report.reasons[0].kind is InvalidationKind.LOCKFILE_CHANGED
    assert managed_report.reasons[0].kind is InvalidationKind.MANAGED_FILE_CHANGED
    assert lock_report.reasons[0].sources == (".ai-project/capabilities.lock",)
    assert managed_report.reasons[0].sources == (".ai-project/policy.yaml",)


def test_expected_user_edits_do_not_count_as_managed_drift(tmp_path: Path) -> None:
    baseline = snapshot(tmp_path)
    changeset = proposed_change(
        tmp_path,
        "AGENTS.md",
        ownership=FileOwnership.OBSERVED,
    )

    report = detect_drift(baseline, baseline, changeset)

    assert report.reasons == ()
    assert not report.invalidates_configuration


def test_drift_output_is_stable_and_does_not_include_file_contents(tmp_path: Path) -> None:
    baseline = snapshot(tmp_path)
    changeset = proposed_change(tmp_path, ".ai-project/policy.yaml")

    first = detect_drift(baseline, baseline, changeset)
    second = detect_drift(baseline, baseline, changeset)

    assert first == second
    assert "before\n" not in repr(first)
    assert "after\n" not in repr(first)
