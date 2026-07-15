from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.task_execution_fixture import TaskExecutionFixture
from vibe.workflows.task_runner import TaskRunStatus

pytestmark = pytest.mark.validation

def test_bug_fix_plan_run_records_outcome_and_surfaces_unused_capability(
    tmp_path: Path,
) -> None:
    fixture = TaskExecutionFixture(tmp_path)
    fixture.seed_history(count=2)

    checkpoint = fixture.run(approve=True)

    assert checkpoint.status is TaskRunStatus.COMPLETED
    assert fixture.approval_requests == ["approval"]
    assert fixture.recorded_outcome().verification_passed is True
    evidence = fixture.unused_capability_finding().evidence
    assert evidence[0] == "cap.unused"
    assert set(evidence[1:]) == {"history-1", "history-2", fixture.task_id}


def test_invalidation_mid_run_pauses_and_resumes_from_checkpoint(tmp_path: Path) -> None:
    fixture = TaskExecutionFixture(tmp_path, invalidate_after_phase="inspect")

    paused = fixture.run(approve=True)
    resumed = fixture.run(approve=True, resume=True)

    assert paused.status is TaskRunStatus.INVALIDATED
    assert paused.next_phase_id == "design"
    assert resumed.status is TaskRunStatus.COMPLETED
    assert fixture.app_server.resumed == [paused.codex_thread_id]
    assert fixture.executed_phase_ids.count("inspect") == 1


def test_declined_gate_leaves_no_partial_outcome(tmp_path: Path) -> None:
    fixture = TaskExecutionFixture(tmp_path)

    checkpoint = fixture.run(approve=False)

    assert checkpoint.status is TaskRunStatus.AWAITING_APPROVAL
    assert checkpoint.next_phase_id == "approval"
    assert fixture.outcome_exists() is False
