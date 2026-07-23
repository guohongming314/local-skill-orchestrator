# Default Read-Only Remote Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable safe read-only remote capability discovery by default, classify unusable source responses truthfully, and persist actionable diagnostics without weakening mutation approvals.

**Architecture:** Keep discovery source selection inside the deterministic init command and separate it from candidate trust and installation authorization. Source adapters establish whether a response was successfully parsed; the discovery aggregator derives the overall state, and initialization stores the resulting reports in its existing durable checkpoint.

**Tech Stack:** Python 3.12, Typer, Pydantic, SQLite checkpoints, pytest, Ruff, mypy, Hatchling.

---

### Task 1: Default Read-Only Discovery

**Files:**
- Modify: `src/vibe/commands/init.py`
- Modify: `src/vibe/models/decisions.py`
- Modify: `src/vibe/materialize/templates.py`
- Test: `tests/commands/test_init_apply.py`
- Test: `tests/models/test_decisions.py`

- [ ] **Step 1: Write failing tests**

Add tests proving an ordinary `vibe init` invokes discovery, `--no-remote-discovery`
returns `not-requested`, and the rendered decision identifies discovery as a recommended
default rather than user approval.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/commands/test_init_apply.py tests/models/test_decisions.py -q`

Expected: the default-discovery and provenance assertions fail.

- [ ] **Step 3: Implement the minimal behavior**

Use a paired Typer option with default `True`, honor an explicit blueprint denial, and add
a typed discovery decision/provenance representation while retaining legacy payload
compatibility. Do not alter artifact fetch or runtime network authorization.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/commands/test_init_apply.py tests/models/test_decisions.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/commands/init.py src/vibe/models/decisions.py src/vibe/materialize/templates.py tests/commands/test_init_apply.py tests/models/test_decisions.py
git commit -m "feat: enable read-only discovery by default"
```

### Task 2: Truthful Source Failure Classification

**Files:**
- Modify: `src/vibe/remote/sources.py`
- Test: `tests/remote/test_sources.py`
- Test: `tests/remote/test_discovery.py`

- [ ] **Step 1: Write failing tests**

Add source-adapter tests for empty fallback text, unparseable fallback text, malformed JSON
shapes, and a failed primary request followed by unusable fallback output. Assert `failed`
with a sanitized non-empty message. Keep a valid parsed empty collection as `success`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/remote/test_sources.py tests/remote/test_discovery.py -q`

Expected: empty/unparseable fallback cases incorrectly report success.

- [ ] **Step 3: Implement the minimal behavior**

Make fallback parsing return an explicit parse outcome and raise `SourceRequestError` when
the response is empty or contains no recognizable directory payload. Preserve the primary
and fallback failure class in a bounded diagnostic message without recording response
bodies.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/remote/test_sources.py tests/remote/test_discovery.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/remote/sources.py tests/remote/test_sources.py tests/remote/test_discovery.py
git commit -m "fix: classify unusable discovery responses as failures"
```

### Task 3: Durable Discovery Diagnostics

**Files:**
- Modify: `src/vibe/commands/init.py`
- Test: `tests/commands/test_init_apply.py`
- Test: `tests/workflows/test_checkpoints.py`

- [ ] **Step 1: Write failing tests**

Add an initialization test that injects failed diagnostics, pauses the run, loads its
checkpoint, and asserts the serialized discovery report retains requirement, source,
query, status, and sanitized message. Resume and assert the result remains `search-failed`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/commands/test_init_apply.py tests/workflows/test_checkpoints.py -q`

Expected: no `discovery_reports` entry exists in confirmed checkpoint state.

- [ ] **Step 3: Implement the minimal behavior**

Revise the initialization checkpoint immediately after discovery with the JSON-mode report
payload. Reuse the existing checkpoint mapping and SQLite serialization; do not create a
second audit database or persist raw response content.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/commands/test_init_apply.py tests/workflows/test_checkpoints.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/commands/init.py tests/commands/test_init_apply.py tests/workflows/test_checkpoints.py
git commit -m "feat: persist remote discovery diagnostics"
```

### Task 4: Remove Discovery Approval Friction

**Files:**
- Modify: `bootstrap-skill/SKILL.md`
- Modify: `src/vibe/materialize/capability_manager.py`
- Test: `tests/skills/test_skills.py`
- Test: `tests/materialize/test_templates.py`
- Modify: `tests/fixtures/generated/project.snapshot`

- [ ] **Step 1: Write failing tests**

Assert bootstrap and generated governance guidance instruct automatic read-only search,
never request discovery approval or trusted-source selection, preserve exact result states,
and still require item-specific approval for downloads, installation, execution, and
permission changes.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/skills/test_skills.py tests/materialize/test_templates.py -q`

Expected: old approval wording violates the new assertions.

- [ ] **Step 3: Implement the minimal behavior**

Rewrite only discovery guidance and add the deterministic discovery command contract where
the generated Skill needs it. Leave mutation governance wording intact. Regenerate the
owned fixture snapshot through the repository's existing snapshot test/update mechanism.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/skills/test_skills.py tests/materialize/test_templates.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bootstrap-skill/SKILL.md src/vibe/materialize/capability_manager.py tests/skills/test_skills.py tests/materialize/test_templates.py tests/fixtures/generated/project.snapshot
git commit -m "docs: make capability discovery automatic"
```

### Task 5: End-To-End Verification And Local Codex Refresh

**Files:**
- Modify as required by failures from the verification commands only.

- [ ] **Step 1: Run focused end-to-end tests**

Run: `uv run pytest tests/e2e/test_remote_install_loop.py tests/recommendation/test_readiness.py -q`

Expected: PASS with installation approval boundaries unchanged.

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Run static and build checks**

Run: `uv run ruff check .`

Run: `uv run mypy src tests`

Run: `uv build`

Expected: every command exits zero.

- [ ] **Step 4: Refresh the local Codex Skill and CLI**

Verify the active Codex Skill is a symlink to this repository's `bootstrap-skill`, reinstall
the package editable with `uv tool install --editable . --force`, and run CLI help plus a
temporary-project smoke test showing default discovery and explicit opt-out behavior.

- [ ] **Step 5: Commit any verification-only corrections**

```bash
git add <only-files-corrected-during-verification>
git commit -m "test: verify default remote discovery workflow"
```
