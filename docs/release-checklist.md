# Release checklist

Use this checklist for every release candidate. Do not publish from this repository automatically.

## Reproducible quality gates

- [ ] Install locked dependencies: `uv sync --locked --all-groups`.
- [ ] Run Bootstrap Skill and project Skill validation: `uv run pytest tests/skills/test_skills.py tests/e2e`.
- [ ] Verify blank web-project browser capability routing: configured Chrome DevTools MCP is selected; without a browser provider, Playwright and Chrome DevTools recommendations are ranked and explained (`uv run pytest tests/e2e/test_init.py -k blank_web`).
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
