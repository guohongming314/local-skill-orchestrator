from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from tests.e2e.hard_routing_fixture import HardRoutingTaskFixture


def test_bug_fix_gateway_exposes_only_each_phase_tools_and_audits_blocked_calls(
    tmp_path: Path,
) -> None:
    fixture = HardRoutingTaskFixture(tmp_path)

    checkpoint = fixture.run(gateway_enabled=True)

    assert checkpoint.status == "completed"
    assert fixture.visible_tools_by_phase == {
        "investigate": ("codegraph_explore", "repository_search"),
        "regression-test": ("browser_snapshot", "browser_validate"),
    }
    assert fixture.audit_events == [
        ("browser_validate", "tool is not allowlisted"),
        ("codegraph_explore", "tool is not allowlisted"),
    ]


def test_disabling_gateway_preserves_soft_routing_tool_visibility(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    fixture = HardRoutingTaskFixture(tmp_path)

    checkpoint = fixture.run(gateway_enabled=False)

    assert checkpoint.status == "completed"
    assert fixture.visible_tools_by_phase == {
        "investigate": fixture.all_tool_names,
        "regression-test": fixture.all_tool_names,
    }
    assert fixture.audit_events == []
    assert [
        record.message
        for record in caplog.records
        if "hard tool isolation unavailable" in record.message
    ] == [
        "Hard routing gateway is not configured; hard tool isolation unavailable, "
        "using soft routing."
    ]


def test_concurrent_gateway_sessions_have_disjoint_tool_inventories(tmp_path: Path) -> None:
    fixture = HardRoutingTaskFixture(tmp_path)

    inventories = anyio.run(fixture.concurrent_disjoint_inventories)

    assert inventories == {
        "investigate-thread": ("codegraph_explore", "repository_search"),
        "regression-thread": ("browser_snapshot", "browser_validate"),
    }
