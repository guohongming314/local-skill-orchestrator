# Codex-native capability validation round 0002

- Schema version: 1
- Date: 2026-07-16 (Asia/Shanghai)
- Validation revision: `808245ce4c9cd10138410f2f2a2069cb50bbf76e`
- Python: 3.12.13
- Codex surface: `codex-cli 0.144.3`, non-interactive `codex exec`
- Overall status: **FAIL — not release-ready**
- Open remediation Epics: 1 (`E18`, issue `#143`)
- Expectation changes: the user-approved Codex-conversation-native design replaces
  the prior E17 row set with stable `NATIVE-*`, `GOV-01`, and `QUALITY-01` IDs;
  mappings are recorded below and in the JSON report.

## Expectation evidence

| ID | Expectation | Status | Evidence |
| --- | --- | --- | --- |
| NATIVE-01 | Initialized repository Skills are discoverable through Codex-native `.agents/skills` paths, carry valid metadata, bind selected user Skills, and do not mandate `vibe run`. | PASS | `tests/e2e/test_codex_native_project_experience.py::test_init_generates_codex_native_discoverable_project_capabilities` |
| NATIVE-02 | A real installed Codex implicitly selects and loads the matching project debugging Skill without a user-entered `vibe` command. | FAIL | Automated boundary: `tests/e2e/test_codex_native_project_experience.py::test_sufficient_existing_capabilities_do_not_invoke_vibe_task_router`; the real-Codex attempt below failed authentication before Skill discovery, so no native-selection claim is made. |
| NATIVE-03 | In a real Codex conversation, an approved missing capability is installed project-locally and the original conversation continues. | FAIL | Automated boundary: `tests/e2e/test_codex_native_project_experience.py::test_missing_capability_install_stays_in_current_codex_conversation`; the real smoke failed before reaching the gap/install step. |
| NATIVE-04 | Real ordinary native work and approved gap installation start no nested Codex task process or thread. | FAIL | Automated boundaries: `tests/e2e/test_codex_native_project_experience.py::test_sufficient_existing_capabilities_do_not_invoke_vibe_task_router`; `tests/e2e/test_codex_native_project_experience.py::test_missing_capability_install_stays_in_current_codex_conversation`; `tests/e2e/test_codex_native_project_experience.py::test_nested_codex_boundaries_are_recorded_and_rejected`. Authentication prevented observing either real task flow. |
| NATIVE-05 | Optional approved Hook governance exposes only managed events, preserves trust bindings, adds no prompt-submit routing, and does not change native Skill discovery. | PASS | `tests/e2e/test_codex_native_project_experience.py::test_optional_hook_governance_does_not_change_native_skill_discovery`; `tests/doctor/test_checks.py::test_doctor_reports_project_hook_security_drift`; `tests/doctor/test_checks.py::test_doctor_reports_widened_hook_permissions` |
| GOV-01 | Capability security and governance retain approval, provenance, digest, project-boundary, update, audit, reconciliation, and organization-policy controls. | PASS | `tests/validation/test_security_gates.py::test_install_bypasses_fail_closed_with_explainable_refusals`; `tests/validation/test_security_gates.py::test_permission_expansion_and_org_policy_bypasses_are_audited`; `tests/validation/test_security_gates.py::test_malicious_skill_is_scanned_rejected_and_never_recommended`; `tests/validation/test_security_gates.py::test_seeded_credentials_never_appear_in_serialized_artifacts`; `tests/e2e/test_remote_install_loop.py::test_digest_tampered_remote_candidate_is_blocked`; `tests/commands/test_update.py::test_widened_permission_upgrade_blocks_until_reapproved`; `tests/commands/test_audit.py::test_seeded_events_produce_filtered_ordered_json_output`; `tests/commands/test_reconcile.py::test_stack_drift_offers_both_resolutions_and_applies_accept_reality`; `tests/resolver/test_org_policy.py::test_org_remote_approvals_filter_publishers_without_bypassing_l_consent` |
| QUALITY-01 | The consolidated acceptance matrix, complete test suite, lint, strict typing, and build gates pass for the validation revision. | PASS | `docs/evaluation/acceptance-matrix.md`; `tests/validation/test_matrix.py::test_acceptance_matrix_covers_all_expectations_with_existing_tests`; commands and artifacts below. |

## Fresh automated results

- `uv sync --locked --all-groups`: PASS; `uv.lock` hash remained
  `662020fa60eb0828068f8d68b87f448d84e44aa1` before and after.
- `uv run pytest tests/skills tests/inventory/test_agent_skill.py tests/materialize tests/e2e/test_codex_native_project_experience.py -q`: PASS, 84 tests.
- `uv run pytest tests/doctor tests/remote tests/validation/test_security_gates.py -q`: PASS, 64 tests.
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

Remediation `E18` / issue `#143` remains OPEN for `NATIVE-02`, `NATIVE-03`, and
`NATIVE-04`: authenticate the installed Codex,
repeat the attended smoke through implicit Skill loading and the approved
project-local gap flow, record the observer/session evidence, and create a new
complete validation round.

## Expectation replacement decision

The prior `E17-1` through `E17-7` row set is not redefined in this round. The
user-approved conversation-native design replaced it with the five native
expectations plus consolidated governance and quality expectations above.
Decision evidence is the `Approval record` in
`docs/superpowers/specs/2026-07-15-codex-conversation-native-capability-routing-design.md`
(the design revision was introduced at commit `e42168b`) and
`docs/superpowers/plans/2026-07-15-codex-native-capability-governance-implementation-plan.md`
at commit `8dc150d`. JSON records one mapping for each prior stable ID.

| Prior ID | User-approved replacement |
| --- | --- |
| E17-1 | `NATIVE-01` |
| E17-2 | `NATIVE-02`, `NATIVE-03` |
| E17-3 | `NATIVE-01`, `QUALITY-01` |
| E17-4 | `NATIVE-02`, `NATIVE-03`, `NATIVE-04`, `QUALITY-01` |
| E17-5 | `NATIVE-04`, `NATIVE-05`, `GOV-01` |
| E17-6 | `GOV-01` |
| E17-7 | `NATIVE-01` through `NATIVE-05`, `GOV-01`, `QUALITY-01` |

## Release record

- Commit validated: `808245ce4c9cd10138410f2f2a2069cb50bbf76e`
- Python: 3.12.13
- CI run: not available; local validation only
- Task-routing sample digest:
  `7d2980d8be18347720cef8397392669276de7dbbd6f093f6fcd7bacb2bf2636e`
- Task-routing threshold schema: version 1,
  `tests/evaluation/task-routing/thresholds.json`
- Artifacts: sdist
  `0df52741b1812040da7fe2247152f0fda6aa820fe1e995d523c438fad11ce7c9`;
  wheel `e30c54eac92ce84f7c2a9a71cbd04b1cd972cbdda66424b7ce905d66e5d5e29e`
- Reviewer: automated independent spec/quality review completed; human release
  reviewer pending
- Rollback owner: pending project maintainer/user
- Known limitations: attended real-Codex implicit Skill selection, same-thread
  gap installation, and absence of nested work in those real flows remain
  unverified because installed authentication returned HTTP 401.

## Release-gate expectation

The latest-round gate is expected to fail truthfully on `NATIVE-02`; a passing gate
would be incorrect until the attended real-Codex evidence exists.
Fresh command output: `release gate FAIL: NATIVE-02 is FAIL` (exit 1).
