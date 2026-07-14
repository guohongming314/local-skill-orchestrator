# E17 validation round 0001

- Schema version: 1
- Date: 2026-07-15
- Open remediation Epics: 0
- Expectation changes: none

| ID | Expectation | Status | Evidence |
| --- | --- | --- | --- |
| E17-1 | Blank web project recommends and binds browser verification | PASS | `tests/e2e/test_init.py` |
| E17-2 | Capability gaps are explained and local choices remain reversible | PASS | `tests/resolver/test_local.py`; `tests/materialize/test_writer.py` |
| E17-3 | Initialization covers project goal, stage, risk, constraints, permissions, and preferences | PASS | `tests/conversation/test_interview.py` |
| E17-4 | Planned tasks are phase-gated with outcome and doctor support | PASS | `tests/workflows/test_task_graph.py`; `tests/doctor/test_checks.py` |
| E17-5 | Hard routing exposes only capsule-selected tools | PASS | `tests/compiler/test_context.py` |
| E17-6 | Lifecycle governance re-approves permission expansion | PASS | `tests/codex/test_approvals.py` |
| E17-7 | Design success criteria are traceable | PASS | `docs/evaluation/task-routing-baseline.md`; `tests/e2e/` |
