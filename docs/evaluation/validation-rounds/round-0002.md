# Codex-native capability validation round 0002

- Schema version: 1
- Date: 2026-07-16 (Asia/Shanghai)
- Validation revision: `808245ce4c9cd10138410f2f2a2069cb50bbf76e`
- Python: 3.12.13
- Codex surface: `codex-cli 0.144.3`, non-interactive `codex exec`
- Overall status: **FAIL — not release-ready**
- Open remediation Epics: 1 (`E18`, issue `#143`)
- Expectation changes: none

## Expectation evidence

| ID | Expectation | Status | Evidence |
| --- | --- | --- | --- |
| E17-1 | Initialized repository Skills are discoverable through Codex-native `.agents/skills` paths, carry valid metadata, bind selected user Skills, and do not mandate `vibe run`. | PASS | `tests/e2e/test_codex_native_project_experience.py::test_init_generates_codex_native_discoverable_project_capabilities` |
| E17-2 | A real installed Codex implicitly selects and loads the matching project debugging Skill without a user-entered `vibe` command. | FAIL | Automated boundary: `tests/e2e/test_codex_native_project_experience.py::test_sufficient_existing_capabilities_do_not_invoke_vibe_task_router`; the real-Codex attempt below failed authentication before Skill discovery, so no native-selection claim is made. |
| E17-3 | An approved missing capability is installed project-locally and the original Codex conversation continues. | PASS | `tests/e2e/test_codex_native_project_experience.py::test_missing_capability_install_stays_in_current_codex_conversation` |
| E17-4 | Ordinary native tasks and approved gap installation start no nested Codex task process or thread at the tested host boundary. | PASS | `tests/e2e/test_codex_native_project_experience.py::test_sufficient_existing_capabilities_do_not_invoke_vibe_task_router`; `tests/e2e/test_codex_native_project_experience.py::test_missing_capability_install_stays_in_current_codex_conversation`; `tests/e2e/test_codex_native_project_experience.py::test_nested_codex_boundaries_are_recorded_and_rejected` |
| E17-5 | Optional approved Hook governance exposes only managed events, preserves trust bindings, and does not change native Skill discovery. | PASS | `tests/e2e/test_codex_native_project_experience.py::test_optional_hook_governance_does_not_change_native_skill_discovery`; `tests/doctor/test_checks.py::test_doctor_reports_project_hook_security_drift`; `tests/doctor/test_checks.py::test_doctor_reports_widened_hook_permissions` |
| E17-6 | Capability security and governance retain approval, provenance, digest, project-boundary, update, audit, reconciliation, and organization-policy controls. | PASS | `tests/validation/test_security_gates.py::test_install_bypasses_fail_closed_with_explainable_refusals`; `tests/validation/test_security_gates.py::test_permission_expansion_and_org_policy_bypasses_are_audited`; `tests/validation/test_security_gates.py::test_malicious_skill_is_scanned_rejected_and_never_recommended`; `tests/validation/test_security_gates.py::test_seeded_credentials_never_appear_in_serialized_artifacts`; `tests/e2e/test_remote_install_loop.py::test_digest_tampered_remote_candidate_is_blocked`; `tests/commands/test_update.py::test_widened_permission_upgrade_blocks_until_reapproved`; `tests/commands/test_audit.py::test_seeded_events_produce_filtered_ordered_json_output`; `tests/commands/test_reconcile.py::test_stack_drift_offers_both_resolutions_and_applies_accept_reality`; `tests/resolver/test_org_policy.py::test_org_remote_approvals_filter_publishers_without_bypassing_l_consent` |
| E17-7 | The consolidated acceptance matrix, complete test suite, lint, strict typing, and build gates pass for the validation revision. | PASS | `docs/evaluation/acceptance-matrix.md`; `tests/validation/test_matrix.py::test_acceptance_matrix_covers_all_expectations_with_existing_tests`; commands and artifacts below. |

## Fresh automated results

- `uv sync --locked --all-groups`: PASS; `uv.lock` hash remained
  `662020fa60eb0828068f8d68b87f448d84e44aa1` before and after.
- Focused native suite: PASS, 84 tests.
- Security/governance suite: PASS, 64 tests.
- `uv run pytest -m validation`: PASS, 105 passed and 403 deselected.
- `uv run pytest`: PASS, 508 passed in 114.52 seconds in the final post-report run.
- `uv run ruff check .`: PASS.
- `uv run mypy src tests`: PASS, no issues in 240 source files. The first run
  exposed 37 branch-caused errors in seven new or modified test files; typing-only
  corrections are isolated in commit `808245c`, and 77 affected tests passed.
- `uv build`: PASS. SHA-256:
  - sdist: `0df52741b1812040da7fe2247152f0fda6aa820fe1e995d523c438fad11ce7c9`
  - wheel: `e30c54eac92ce84f7c2a9a71cbd04b1cd972cbdda66424b7ce905d66e5d5e29e`
- `git diff --check`: PASS.
- Task-routing sample digest remained
  `7d2980d8be18347720cef8397392669276de7dbbd6f093f6fcd7bacb2bf2636e`.

## Real-Codex smoke attempt — PENDING

The smoke used temporary fixture commit
`e52e4c888c0bc547760500f095eafc63a5bb5620` and a temporary `CODEX_HOME`
containing only a copy of the existing authentication file. It did not read or
write user-global Codex configuration. The prompt asked Codex to fix a failing
calculator test using a matching installed `systematic-debugging` Skill
implicitly, without running `vibe` or starting nested Codex work.

`codex exec --json --ephemeral --ignore-user-config -s workspace-write` launched
one top-level thread (`019f698c-1d92-71f2-a2f3-7ba27fe7b0b5`) and then failed
before any model turn or Skill load. Both WebSocket and HTTPS transports returned
HTTP 401 `invalid_api_key`. The fixture remained unchanged, the required
`.smoke-skill-loaded.json` selection marker was absent, and no user entered a
`vibe` command. Because authentication prevented observation of native implicit
Skill selection, this is not a passed attended smoke and provides no evidence
about nested task processes or thread continuity after task execution.

Remediation `E18` / issue `#143` remains OPEN: authenticate the installed Codex,
repeat the attended smoke through implicit Skill loading and the approved
project-local gap flow, record the observer/session evidence, and create a new
complete validation round.

## Release-gate expectation

The latest-round gate is expected to fail truthfully on `E17-2`; a passing gate
would be incorrect until the attended real-Codex evidence exists.
