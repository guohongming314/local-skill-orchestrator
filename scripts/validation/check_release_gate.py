#!/usr/bin/env python3
"""Fail unless the latest validation round is release-valid."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_COUNT = 7
VALID_STATUSES = {"PASS", "FAIL"}


class GateError(ValueError):
    """A validation report does not satisfy the release gate."""


def _load_latest(rounds: Path) -> tuple[Path, dict[str, Any]]:
    candidates = sorted(rounds.glob("round-*.json"))
    if not candidates:
        raise GateError(f"no versioned round reports found in {rounds}")
    path = candidates[-1]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise GateError(f"{path.name} must contain a JSON object")
    return path, value


def _require_list(report: dict[str, Any], field: str) -> list[Any]:
    value = report.get(field)
    if not isinstance(value, list):
        raise GateError(f"{field} must be a list")
    return value


def check_release_gate(rounds: Path) -> Path:
    """Return the latest report path when it satisfies the release gate."""
    path, report = _load_latest(rounds)
    if report.get("schema_version") != 1:
        raise GateError(f"{path.name} has unsupported schema_version")

    markdown_path = path.with_suffix(".md")
    if not markdown_path.is_file():
        raise GateError(f"{path.name} has no matching markdown report")

    expectations = _require_list(report, "expectations")
    if len(expectations) != EXPECTED_COUNT:
        raise GateError(f"expected {EXPECTED_COUNT} expectation rows, found {len(expectations)}")

    seen_ids: set[str] = set()
    for row in expectations:
        if not isinstance(row, dict):
            raise GateError("each expectation row must be an object")
        expectation_id = row.get("id")
        if not isinstance(expectation_id, str) or not expectation_id:
            raise GateError("each expectation row needs a non-empty id")
        if expectation_id in seen_ids:
            raise GateError(f"duplicate expectation id {expectation_id}")
        seen_ids.add(expectation_id)
        status = row.get("status")
        if status not in VALID_STATUSES:
            raise GateError(f"{expectation_id} has invalid status {status!r}")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(link, str) and link for link in evidence
        ):
            raise GateError(f"{expectation_id} needs at least one evidence link")
        if status != "PASS":
            raise GateError(f"{expectation_id} is {status}")

    for epic in _require_list(report, "remediation_epics"):
        if not isinstance(epic, dict):
            raise GateError("each remediation epic must be an object")
        epic_id = epic.get("id", "<unknown>")
        if epic.get("status") != "CLOSED":
            raise GateError(f"open remediation epic {epic_id}")
        linked = epic.get("expectations")
        if not isinstance(linked, list) or not linked:
            raise GateError(f"remediation epic {epic_id} has no linked expectations")

    _require_list(report, "expectation_changes")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=Path, required=True)
    args = parser.parse_args()
    try:
        path = check_release_gate(args.rounds)
    except GateError as error:
        print(f"release gate FAIL: {error}", file=sys.stderr)
        return 1
    print(f"{path.name}: release gate PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
