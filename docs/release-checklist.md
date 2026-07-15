# Release checklist

Use this checklist for every release candidate. Do not publish from this repository automatically.

## Reproducible quality gates

- [ ] Install locked dependencies: `uv sync --locked --all-groups`.
- [ ] Run Bootstrap Skill and project Skill validation: `uv run pytest tests/skills/test_skills.py tests/e2e`.
- [ ] Verify conversational init acceptance for blank and existing repositories, including revision, locked decisions, recommended defaults, structured-output fallback, cancellation, resume, review, dry-run, and apply: `uv run pytest tests/e2e/test_conversational_init.py`.
- [ ] Verify the task execution loop covers plan → phase-gated run → persisted outcome → Doctor insight, plus resumable invalidation and declined-gate safety: `uv run pytest tests/e2e/test_task_execution_loop.py`.
- [ ] Verify hard-routing acceptance with fake MCP upstreams: phase transitions expose only capsule-selected tools, blocked calls are audited, concurrent sessions remain disjoint, and disabling the gateway preserves soft-routing visibility: `uv run pytest tests/e2e/test_hard_routing_tool_visibility.py`.
- [ ] Verify blank web-project browser capability routing: configured Chrome DevTools MCP is selected; without a browser provider, Playwright and Chrome DevTools recommendations are ranked and explained (`uv run pytest tests/e2e/test_init.py -k blank_web`).
- [ ] Verify the offline remote-capability loop: explained browser gap → fixture-registry candidate → explicit approval → digest-pinned install → init binding → healthy Doctor → uninstall/reconcile baseline, including unapproved, digest-tampered, offline, and discovery-disabled cases (`uv run pytest tests/e2e/test_remote_install_loop.py`).
- [ ] Run the consolidated E11–E16 acceptance matrix and cross-epic fixtures; review `tests/results/validation-summary.json`: `uv run pytest -m validation`.
- [ ] Run the security and permission-gate adversarial audit, including install/update/policy bypasses, malicious capability content, and seeded-secret artifact scans: `uv run pytest -m validation tests/validation/test_security_gates.py`.
- [ ] Run the full suite: `uv run pytest`.
- [ ] Verify the latest E17 validation round is all-PASS with zero open remediation Epics: `uv run python scripts/validation/check_release_gate.py --rounds docs/evaluation/validation-rounds`.
- [ ] Enforce reviewed task-routing evaluation thresholds with the versioned offline runner.
- [ ] Confirm `tests/results/task-routing.json` is unchanged after evaluation.
- [ ] Run `uv run ruff check .`.
- [ ] Run strict typing: `uv run mypy src tests`.
- [ ] Build source and wheel distributions: `uv build`.
- [ ] Run `git diff --check` and confirm the release worktree is clean.

## Required human review

- [ ] **Security:** review command execution, network access, secret handling, permission deltas, and approval boundaries.
- [ ] **Privacy:** confirm repository data and memory-provider leads remain local unless explicitly approved; inspect artifacts for sensitive data.
- [ ] **Rollback:** exercise cancellation/resume and rollback paths; document how to restore generated configuration and the prior package version.
- [ ] **Manual core-flow review:** perform blank-project init, existing-project init, dry-run, apply, repeat apply, plan, and Doctor checks.
- [ ] Review the Bootstrap Skill guidance/CLI policy boundary and verify no Skill text can bypass deterministic policy.

## Release record

Record the commit, Python version, artifact hashes, CI run, task-routing sample digest, threshold schema version, reviewer, known limitations, and rollback owner.
