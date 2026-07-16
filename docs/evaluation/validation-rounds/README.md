# Validation rounds and remediation protocol

This directory is the release record for E17 validation. Reports are immutable,
versioned pairs named `round-NNNN.md` and `round-NNNN.json`; the largest filename
is the latest round. The Markdown file is the reviewed human record and the JSON
file is the CI-checkable equivalent. Both contain exactly one row for each
validation round's seven reviewed release expectations, a `PASS` or `FAIL`, and
links to evidence such as exact pytest node IDs, a real-environment smoke
result, or an evaluation report. A required smoke that cannot reach the
behavior under test is `FAIL`, not inferred from an automated host fixture; its
blocker must be recorded with an open remediation.

## JSON schema (version 1)

```json
{
  "schema_version": 1,
  "round": 1,
  "expectations": [
    {"id": "E17-1", "expectation": "...", "status": "PASS", "evidence": ["path-or-url"]}
  ],
  "remediation_epics": [
    {"id": "E18", "issue": 147, "status": "OPEN", "expectations": ["E17-2"]}
  ],
  "expectation_changes": [
    {"expectation": "E17-2", "decision": "...", "decided_by": "user", "evidence": "..."}
  ]
}
```

Statuses are uppercase `PASS` or `FAIL`. Evidence arrays must be non-empty.
Remediation statuses are `OPEN` or `CLOSED`, and every remediation Epic links the
expectation rows it fixes. `expectation_changes` is empty unless the user changes
an expectation.

## Failure remediation loop

1. Review all failed rows and cluster failures by root cause, not by symptom.
2. In a reviewed design step, create one remediation Epic per root cause, using
   the standard issue template in the issue-breakdown design. Number them E18,
   E19, and onward. Never create these Epics unattended.
3. Every remediation Epic references the exact failed expectation IDs it fixes;
   record the Epic and those IDs in the round JSON and Markdown report.
4. After every open remediation Epic is closed, run the **entire** validation
   round again: automated acceptance, real-environment smoke, evaluation, and
   security. Partial re-runs can diagnose a fix but are not release-valid.
5. Commit a new report pair. Keep prior rounds unchanged and repeat until all
   seven rows pass with zero open remediation Epics.

Agents may propose changing, weakening, or removing an expectation, but may not
make that decision. Such a change requires an explicit user decision, recorded
in both reports under `expectation_changes` with decision evidence.

## Release gate

Run:

```bash
uv run python scripts/validation/check_release_gate.py --rounds docs/evaluation/validation-rounds
```

The gate selects the latest JSON report and requires schema version 1, its
matching Markdown report, exactly seven evidence-backed `PASS` rows, and zero
open remediation Epics. Missing, malformed, incomplete, or failing reports block
the release.
