# E17 validation round 0001

- Schema version: 1
- Date: 2026-07-15
- Open remediation Epics: 0
- Expectation changes: none
- Revision note: evidence citations corrected 2026-07-15 during oversight review — the original
  report cited adjacent-but-weaker tests for E17-2/4/5/6/7 (e.g. `tests/resolver/test_local.py`
  instead of the remote-install e2e). Statuses were independently re-verified against the
  corrected evidence before this revision (`uv run pytest -m validation`: 88 passed; targeted
  runs of all corrected evidence files: 45 passed). Expectation wording restored to the seven
  expectations exactly as listed in Epic #141.

| ID | Expectation | Status | Evidence |
| --- | --- | --- | --- |
| E17-1 | Blank web project + installed Chrome DevTools MCP: `vibe init` recommends/binds browser verification (E11) | PASS | `tests/e2e/test_init.py` |
| E17-2 | Missing capability → explained remote candidates → approved install → locked, verified, reversible (E12) | PASS | `tests/e2e/test_remote_install_loop.py`; `tests/remote/test_install.py` |
| E17-3 | `vibe init` runs as a real conversation covering goal, stage, risk, constraints, permissions, preferences (E13) | PASS | `tests/e2e/test_conversational_init.py`; `tests/conversation/test_interview.py` |
| E17-4 | A planned task executes phase-gated with outcome recording and doctor insights (E14) | PASS | `tests/e2e/test_task_execution_loop.py`; `tests/workflows/test_task_runner.py` |
| E17-5 | Sessions see only capsule-selected tools when hard routing is enabled (E15) | PASS | `tests/e2e/test_hard_routing_tool_visibility.py`; `tests/routing/test_gateway.py` |
| E17-6 | Update/reconcile/audit lifecycle works with re-approval on permission expansion (E16) | PASS | `tests/commands/test_update.py`; `tests/commands/test_audit.py`; `tests/commands/test_reconcile.py` |
| E17-7 | Every design success-criteria bullet holds via the traceability matrix | PASS | `docs/evaluation/acceptance-matrix.md`; `docs/evaluation/task-routing-2026-07-15.md`; `tests/validation/test_matrix.py` |

Pending outside this report (per #141): `#143` real-environment smoke requires an attended run;
epics close only after the user signs off on this round.
