from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path("scripts/validation/check_release_gate.py")


def _write_round(
    rounds: Path,
    *,
    statuses: list[str],
    remediation_epics: list[dict[str, Any]] | None = None,
) -> None:
    rounds.mkdir(parents=True)
    expectations = [
        {
            "id": f"E{index}",
            "expectation": f"Expectation {index}",
            "status": status,
            "evidence": [f"evidence/result-{index}.json"],
        }
        for index, status in enumerate(statuses, start=1)
    ]
    report = {
        "schema_version": 1,
        "round": 1,
        "expectations": expectations,
        "remediation_epics": remediation_epics or [],
        "expectation_changes": [],
    }
    (rounds / "round-0001.json").write_text(json.dumps(report), encoding="utf-8")
    (rounds / "round-0001.md").write_text("# Fixture round\n", encoding="utf-8")


def _run(rounds: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--rounds", str(rounds)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_fail_report_blocks_release(tmp_path: Path) -> None:
    rounds = tmp_path / "rounds"
    _write_round(rounds, statuses=["PASS"] * 6 + ["FAIL"])

    result = _run(rounds)

    assert result.returncode != 0
    assert "E7 is FAIL" in result.stderr


def test_all_pass_report_with_zero_open_remediation_epics_allows_release(
    tmp_path: Path,
) -> None:
    rounds = tmp_path / "rounds"
    _write_round(
        rounds,
        statuses=["PASS"] * 7,
        remediation_epics=[{"id": "E18", "issue": 200, "status": "CLOSED", "expectations": ["E2"]}],
    )

    result = _run(rounds)

    assert result.returncode == 0, result.stderr
    assert "round-0001.json: release gate PASS" in result.stdout


def test_open_remediation_epic_blocks_release(tmp_path: Path) -> None:
    rounds = tmp_path / "rounds"
    _write_round(
        rounds,
        statuses=["PASS"] * 7,
        remediation_epics=[{"id": "E18", "issue": 200, "status": "OPEN", "expectations": ["E2"]}],
    )

    result = _run(rounds)

    assert result.returncode != 0
    assert "open remediation epic E18" in result.stderr
