# Codex Native Capability Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make normal Codex conversations use Codex-native Skill discovery and implicit invocation while Vibe handles project capability initialization, project-local installation, supply-chain governance, Hooks, Doctor, and lifecycle management behind the scenes.

**Architecture:** Keep Codex as the only task executor. Extend the existing deterministic inventory and materialization pipeline so initialization produces concise `AGENTS.md`, Codex-native repo Skills with validated `agents/openai.yaml`, project capability requirement and lock files, and optional trusted project Hooks. Replace the generated catch-all `project-development` Skill with a narrow `project-capability-manager`; retain CLI commands as internal/diagnostic APIs and deprecate `vibe run` and the current `vibe plan` as user-facing task entry points.

**Tech Stack:** Python 3.12, Typer, Pydantic v2, PyYAML, pytest, Ruff, mypy, Agent Skills, Codex `AGENTS.md`, Codex Skill metadata, Codex project Hooks.

---

## File structure and ownership

### Files created

- `src/vibe/models/codex_skill.py` — typed Codex-native Skill invocation and dependency metadata.
- `src/vibe/materialize/capability_manager.py` — render the narrow project capability-management Skill and its references.
- `src/vibe/materialize/codex_metadata.py` — render and validate `agents/openai.yaml` for generated repo Skills.
- `src/vibe/materialize/project_hooks.py` — render optional project Hook configuration from approved policy.
- `src/vibe/materialize/skill_binding.py` — copy verified selected Skills into project scope without reading secret-like files.
- `tests/models/test_codex_skill.py` — metadata model tests.
- `tests/materialize/test_capability_manager.py` — generated capability-manager Skill tests.
- `tests/materialize/test_codex_metadata.py` — Codex metadata rendering tests.
- `tests/materialize/test_project_hooks.py` — Hook rendering and trust-digest tests.
- `tests/materialize/test_skill_binding.py` — project-local Skill binding tests.
- `tests/e2e/test_codex_native_project_experience.py` — initialization-to-native-discovery acceptance tests.
- `tests/e2e/codex_native_fixture.py` — fake-host fixture that observes native Skill loading and forbids nested task processes.
- `docs/migration/codex-native-capability-governance.md` — user and maintainer migration guide.

### Files modified

- `src/vibe/models/capability.py` — add Codex-native discovery metadata to `CapabilityManifest`.
- `src/vibe/inventory/adapters/agent_skill.py` — parse `agents/openai.yaml`, invocation policy, and declared MCP dependencies.
- `src/vibe/commands/project_plan.py` — stop excluding the old generated Skill by name and distinguish generated governance Skills from selectable task Skills.
- `src/vibe/materialize/templates.py` — emit requirements, concise project guidance, capability manager, Skill metadata, and Hook policy; stop emitting `project-development` routing files.
- `src/vibe/commands/init.py` — add verified project-local Skill bindings to the initialization ChangeSet.
- `src/vibe/materialize/changeset.py` — support copied Skill directory proposals as normal owned files.
- `src/vibe/doctor/checks.py` — verify Skill metadata, project binding digests, and Hook trust digests.
- `src/vibe/commands/doctor.py` — surface native-discovery and Hook findings.
- `bootstrap-skill/SKILL.md` — describe a Codex-conversation workflow and hide CLI mechanics from the user.
- `bootstrap-skill/agents/openai.yaml` — declare the internal tool dependency and maintain implicit initialization triggering.
- `templates/project-development/SKILL.md.tmpl` — retire or replace with the capability-manager template.
- `tests/skills/test_skills.py` — assert conversation-native behavior and remove CLI-as-user-workflow assertions.
- `tests/materialize/test_templates.py` — update expected generated files and snapshots.
- `tests/fixtures/generated/project.snapshot` — update deterministic generated output.
- `tests/commands/test_init_apply.py` — verify selected Skills are bound project-locally.
- `tests/doctor/test_checks.py` — add metadata, binding, and Hook drift cases.
- `src/vibe/cli.py` — label legacy execution commands as deprecated in help.
- `src/vibe/commands/plan.py` — add deprecation guidance; retain deterministic review behavior for compatibility.
- `src/vibe/commands/run.py` — add deprecation guidance; retain compatibility until removal criteria are met.
- `docs/release-checklist.md` — add real Codex Skill discovery and Hook trust smoke tests.
- `docs/evaluation/acceptance-matrix.md` — replace external-runner expectations with native Codex experience expectations.

---

### Task 1: Model Codex-native Skill discovery metadata

**Files:**
- Create: `src/vibe/models/codex_skill.py`
- Modify: `src/vibe/models/capability.py`
- Create: `tests/models/test_codex_skill.py`
- Modify: `tests/models/test_contracts.py`

- [ ] **Step 1: Write failing metadata model tests**

```python
from pydantic import ValidationError
import pytest

from vibe.models.codex_skill import CodexSkillMetadata, SkillToolDependency


def test_codex_skill_metadata_defaults_to_implicit_invocation() -> None:
    metadata = CodexSkillMetadata()

    assert metadata.allow_implicit_invocation is True
    assert metadata.tool_dependencies == ()


def test_codex_skill_metadata_normalizes_declared_mcp_dependencies() -> None:
    metadata = CodexSkillMetadata(
        allow_implicit_invocation=True,
        tool_dependencies=(
            SkillToolDependency(
                dependency_type="mcp",
                value="openaiDeveloperDocs",
                transport="streamable_http",
                url="https://developers.openai.com/mcp",
            ),
        ),
    )

    assert metadata.tool_dependencies[0].value == "openaiDeveloperDocs"


def test_codex_skill_metadata_rejects_unknown_dependency_types() -> None:
    with pytest.raises(ValidationError):
        SkillToolDependency(dependency_type="shell", value="unsafe")
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
uv run pytest tests/models/test_codex_skill.py -q
```

Expected: collection or import failure because `vibe.models.codex_skill` does not exist.

- [ ] **Step 3: Implement the metadata models**

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SkillToolDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dependency_type: Literal["mcp"]
    value: str = Field(min_length=1)
    description: str | None = None
    transport: Literal["stdio", "streamable_http"] | None = None
    url: str | None = None


class CodexSkillMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allow_implicit_invocation: bool = True
    tool_dependencies: tuple[SkillToolDependency, ...] = ()
```

Add to `CapabilityManifest`:

```python
from vibe.models.codex_skill import CodexSkillMetadata

codex_skill: CodexSkillMetadata | None = None
```

- [ ] **Step 4: Add JSON-schema contract coverage**

Extend `tests/models/test_contracts.py` so the `CapabilityManifest` schema contains `codex_skill`, `allow_implicit_invocation`, and `tool_dependencies`, while non-Skill manifests may leave the field unset.

- [ ] **Step 5: Run model tests**

Run:

```bash
uv run pytest tests/models/test_codex_skill.py tests/models/test_contracts.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/vibe/models/codex_skill.py src/vibe/models/capability.py tests/models/test_codex_skill.py tests/models/test_contracts.py
git commit -m "feat: model Codex-native skill metadata"
```

### Task 2: Parse `agents/openai.yaml` during Skill inventory

**Files:**
- Modify: `src/vibe/inventory/adapters/agent_skill.py`
- Modify: `tests/inventory/test_agent_skill.py`

- [ ] **Step 1: Write failing adapter tests**

Add helpers that create `agents/openai.yaml`, then add:

```python
def test_reads_implicit_invocation_policy_and_mcp_dependencies(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(
        roots,
        "docs-helper",
        "name: docs-helper\ndescription: Use for official API documentation questions",
    )
    agents = skill / "agents"
    agents.mkdir()
    (agents / "openai.yaml").write_text(
        """policy:
  allow_implicit_invocation: false
dependencies:
  tools:
    - type: mcp
      value: openaiDeveloperDocs
      transport: streamable_http
      url: https://developers.openai.com/mcp
""",
        encoding="utf-8",
    )

    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))
    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.codex_skill is not None
    assert result.manifest.codex_skill.allow_implicit_invocation is False
    assert result.manifest.codex_skill.tool_dependencies[0].value == "openaiDeveloperDocs"
    assert "dependency:agents/openai.yaml" in result.verification.details


def test_malformed_openai_metadata_marks_skill_unverified(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(roots, "broken", "name: broken\ndescription: Broken metadata")
    agents = skill / "agents"
    agents.mkdir()
    (agents / "openai.yaml").write_text("policy: []\n", encoding="utf-8")

    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))
    result = adapter.scan(adapter.discover()[0])

    assert not result.verification.verified
    assert any("invalid_openai_metadata" in item for item in result.verification.details)
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
uv run pytest tests/inventory/test_agent_skill.py -q
```

Expected: failures because `AgentSkillAdapter` does not parse `agents/openai.yaml`.

- [ ] **Step 3: Implement safe metadata parsing**

Add `_read_codex_metadata(skill_directory)` that:

1. Returns `CodexSkillMetadata()` when the file is absent.
2. Uses `yaml.safe_load` and validates mappings only.
3. Maps `policy.allow_implicit_invocation` and `dependencies.tools` into the Task 1 models.
4. Adds the metadata bytes to the Skill content digest.
5. Never follows metadata paths outside the Skill directory.
6. Records `dependency:agents/openai.yaml` or `invalid_openai_metadata:<ErrorType>`.

Before the existing `CapabilityManifest(...)` construction, add:

```python
codex_metadata, metadata_details, metadata_bytes = _read_codex_metadata(skill_directory)
digest.update(b"agents/openai.yaml\0")
digest.update(metadata_bytes)
details.extend(metadata_details)
```

Then add `codex_skill=codex_metadata` to the existing constructor without changing its other fields.

- [ ] **Step 4: Run adapter and security regression tests**

Run:

```bash
uv run pytest tests/inventory/test_agent_skill.py tests/validation/test_security_gates.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/inventory/adapters/agent_skill.py tests/inventory/test_agent_skill.py
git commit -m "feat: inventory Codex skill invocation metadata"
```

### Task 3: Generate the narrow project capability manager and concise guidance

**Files:**
- Create: `src/vibe/materialize/capability_manager.py`
- Create: `src/vibe/materialize/codex_metadata.py`
- Modify: `src/vibe/materialize/templates.py`
- Create: `tests/materialize/test_capability_manager.py`
- Create: `tests/materialize/test_codex_metadata.py`
- Modify: `tests/materialize/test_templates.py`
- Modify: `templates/project-development/SKILL.md.tmpl`

- [ ] **Step 1: Write failing rendering tests**

```python
def test_generated_capability_manager_is_not_a_general_task_router() -> None:
    files = render_project_configuration(*inputs()).as_dict()
    skill = files[".agents/skills/project-capability-manager/SKILL.md"]

    assert "when Codex cannot complete a task" in skill
    assert "Do not use for ordinary task classification" in skill
    assert "vibe run" not in skill
    assert ".agents/skills/project-development/SKILL.md" not in files


def test_generated_openai_metadata_allows_implicit_gap_management() -> None:
    files = render_project_configuration(*inputs()).as_dict()
    metadata = yaml.safe_load(
        files[".agents/skills/project-capability-manager/agents/openai.yaml"]
    )

    assert metadata["policy"]["allow_implicit_invocation"] is True
    assert metadata["interface"]["display_name"] == "Project Capability Manager"


def test_generated_agents_guidance_is_concise_and_has_no_router_mandate() -> None:
    files = render_project_configuration(*inputs()).as_dict()
    guidance = files["AGENTS.md.managed"]

    assert "Use Codex-native Skill discovery" in guidance
    assert "Before every project operation" not in guidance
    assert len(guidance.encode("utf-8")) < 2048
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
uv run pytest tests/materialize/test_capability_manager.py tests/materialize/test_codex_metadata.py tests/materialize/test_templates.py -q
```

Expected: missing file keys and old `project-development` assertions fail.

- [ ] **Step 3: Implement the capability-manager renderer**

`render_capability_manager()` must emit this frontmatter and scope:

```markdown
---
name: project-capability-manager
description: Diagnose, recommend, install, replace, update, or remove project-local capabilities when Codex cannot complete a task with currently available skills or tools, when a declared dependency is missing or unhealthy, or when the user asks to manage project capabilities. Do not use for ordinary task classification or when existing capabilities are sufficient.
version: 1.0.0
---

# Project capability management

Use Codex-native Skill discovery for ordinary tasks.

Use this Skill only to:

- explain a verified capability gap;
- inspect unavailable or unhealthy dependencies;
- recommend project-local candidates;
- request approval before installation or permission expansion;
- install, replace, update, disable, or remove a project capability;
- run Doctor after a lifecycle change.

Never start another Codex process and never delegate task execution to `vibe run`.
```

Add references for capability requirements, approved providers, and governance commands. The references may name internal commands because they are instructions for Codex, not user-facing workflow.

- [ ] **Step 4: Implement Codex metadata rendering**

`render_openai_metadata()` returns deterministic YAML:

```yaml
interface:
  display_name: Project Capability Manager
  short_description: Manage missing or unhealthy project capabilities
  default_prompt: Use $project-capability-manager to diagnose and resolve this project capability issue.
policy:
  allow_implicit_invocation: true
```

- [ ] **Step 5: Replace generated project files**

In `render_project_configuration()`:

1. Remove `.agents/skills/project-development/**`.
2. Add `.agents/skills/project-capability-manager/SKILL.md`.
3. Add `.agents/skills/project-capability-manager/agents/openai.yaml`.
4. Add narrow references.
5. Add an in-memory `AGENTS.md.managed` entry consumed by `init.py`, not written literally as a side file.

- [ ] **Step 6: Update structural validation tests**

Change expected capability ID from `skill.project-development` to `skill.project-capability-manager`; assert the manager description contains both positive and negative trigger conditions.

- [ ] **Step 7: Run rendering tests and update the deterministic snapshot**

Run:

```bash
uv run pytest tests/materialize/test_capability_manager.py tests/materialize/test_codex_metadata.py tests/materialize/test_templates.py tests/skills/test_skills.py -q
```

Expected before snapshot update: only the byte snapshot fails. Review the generated file set, then update the fixture exactly with:

```bash
uv run python -c 'from tests.materialize.test_templates import FIXTURE, inputs; from vibe.materialize.templates import render_project_configuration; FIXTURE.write_bytes(render_project_configuration(*inputs()).snapshot_bytes())'
```

Rerun and expect PASS.

- [ ] **Step 8: Commit**

```bash
git add src/vibe/materialize/capability_manager.py src/vibe/materialize/codex_metadata.py src/vibe/materialize/templates.py templates/project-development/SKILL.md.tmpl tests/materialize tests/skills/test_skills.py tests/fixtures/generated/project.snapshot
git commit -m "feat: generate Codex-native capability governance"
```

### Task 4: Emit abstract capability requirements and richer lock metadata

**Files:**
- Modify: `src/vibe/materialize/templates.py`
- Modify: `src/vibe/models/capability.py`
- Modify: `tests/materialize/test_templates.py`
- Modify: `tests/models/test_contracts.py`

- [ ] **Step 1: Write failing configuration tests**

```python
def test_renders_supplier_independent_capability_requirements() -> None:
    files = render_project_configuration(*inputs()).as_dict()
    requirements = yaml.safe_load(files[".ai-project/capability-requirements.yaml"])

    quality = next(
        item for item in requirements["requirements"] if item["capability"] == "quality.gates"
    )
    assert quality["selected_provider"] is None
    assert quality["reasons"]
    assert quality["verification"]


def test_lock_records_native_skill_invocation_and_dependencies() -> None:
    files = render_project_configuration(*inputs()).as_dict()
    lock = yaml.safe_load(files[".ai-project/capabilities.lock"])

    provider = lock["providers"][0]
    assert "codex_skill" in provider
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
uv run pytest tests/materialize/test_templates.py tests/models/test_contracts.py -q
```

Expected: missing requirements file and lock metadata.

- [ ] **Step 3: Add rendered requirement models**

Create `RenderedCapabilityRequirement` and `RenderedCapabilityRequirements` in `templates.py`:

```python
class RenderedCapabilityRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: str
    strength: str
    reasons: tuple[str, ...]
    verification: tuple[str, ...]
    selected_provider: None = None


class RenderedCapabilityRequirements(VersionedModel):
    requirements: tuple[RenderedCapabilityRequirement, ...]
```

Change `render_project_configuration()` to accept one new keyword-only argument:

```python
def render_project_configuration(
    blueprint: Blueprint,
    resolution_plan: ResolutionPlan,
    inventory: InventoryResult,
    *,
    requirements: tuple[AbstractCapabilityRequirement, ...],
) -> RenderedProject:
```

Do not pass `ProjectPlan` into the materialization layer and do not recompute requirements there.

- [ ] **Step 4: Extend the lock entry**

Add:

```python
codex_skill: CodexSkillMetadata | None = None
```

Populate it from selected manifests. Preserve `exclude_none=True` so non-Skill providers stay compact.

- [ ] **Step 5: Update all render call sites**

Update `src/vibe/commands/init.py`, test fixtures, and helpers to pass `project_plan.requirements`. Do not recompute requirements in the renderer.

- [ ] **Step 6: Run materialization, init, and schema tests**

Run:

```bash
uv run pytest tests/materialize tests/commands/test_init_apply.py tests/commands/test_init_model_only.py tests/models/test_contracts.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/vibe/materialize/templates.py src/vibe/models/capability.py src/vibe/commands/init.py tests/materialize tests/commands/test_init_apply.py tests/commands/test_init_model_only.py tests/models/test_contracts.py tests/fixtures/generated/project.snapshot
git commit -m "feat: materialize project capability requirements"
```

### Task 5: Bind selected user Skills into project scope

**Files:**
- Create: `src/vibe/materialize/skill_binding.py`
- Modify: `src/vibe/commands/init.py`
- Modify: `src/vibe/materialize/changeset.py`
- Create: `tests/materialize/test_skill_binding.py`
- Modify: `tests/commands/test_init_apply.py`
- Modify: `src/vibe/commands/project_plan.py`

- [ ] **Step 1: Write failing binding tests**

```python
def test_builds_project_binding_for_selected_verified_user_skill(tmp_path: Path) -> None:
    source = make_skill(tmp_path / "user", "systematic-debugging")
    manifest = skill_manifest(source, scope=CapabilityScope.USER, verified=True)

    proposals = build_skill_binding_proposals(
        project_root=tmp_path / "project",
        manifests=(manifest,),
    )

    paths = {proposal.relative_path for proposal in proposals}
    assert ".agents/skills/systematic-debugging/SKILL.md" in paths


def test_binding_copies_declared_local_dependencies_and_openai_metadata(tmp_path: Path) -> None:
    source = make_skill_with_reference_and_metadata(tmp_path / "user", "review-security")
    manifest = skill_manifest(source, scope=CapabilityScope.USER, verified=True)

    proposals = build_skill_binding_proposals(tmp_path / "project", (manifest,))

    paths = {proposal.relative_path for proposal in proposals}
    assert ".agents/skills/review-security/references/checklist.md" in paths
    assert ".agents/skills/review-security/agents/openai.yaml" in paths


def test_binding_refuses_unverified_or_secret_like_skill_content(tmp_path: Path) -> None:
    source = make_skill_with_secret_reference(tmp_path / "user", "unsafe")
    manifest = skill_manifest(source, scope=CapabilityScope.USER, verified=False)

    with pytest.raises(ValueError, match="verified"):
        build_skill_binding_proposals(tmp_path / "project", (manifest,))
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
uv run pytest tests/materialize/test_skill_binding.py tests/commands/test_init_apply.py -q
```

Expected: import failure because binding support does not exist.

- [ ] **Step 3: Implement safe project binding**

`build_skill_binding_proposals()` must:

1. Accept only selected, verified `CapabilityKind.SKILL` manifests.
2. Copy only `SKILL.md`, `agents/openai.yaml`, and local files already included in the verified Skill digest.
3. Refuse symlinks that resolve outside the Skill directory.
4. Refuse secret-like filenames using the same policy as `AgentSkillAdapter`.
5. Preserve bytes exactly.
6. Produce deterministic `ChangeProposal` objects under `.agents/skills/<name>/`.
7. Skip providers already scoped to the same project path.

Expose the adapter's safe dependency list through a shared helper rather than duplicating regex rules.

- [ ] **Step 4: Integrate bindings into init ChangeSets**

In `_project_changeset()`:

```python
selected_manifests = selected_capability_manifests(inventory, resolution)
binding_proposals = build_skill_binding_proposals(root, selected_manifests)
changeset = build_changeset(
    root,
    proposals=(*rendered_proposals, *binding_proposals),
    commands=commands,
)
```

Ensure the generated capability manager is excluded from source inventory by capability ID or a generated marker, not the obsolete directory name `project-development`.

- [ ] **Step 5: Verify repeat initialization is idempotent**

Add an init test that runs apply twice and asserts no second-run changes for bound Skills and no duplicate Skill discoveries.

- [ ] **Step 6: Run focused and security tests**

Run:

```bash
uv run pytest tests/materialize/test_skill_binding.py tests/commands/test_init_apply.py tests/inventory/test_agent_skill.py tests/validation/test_security_gates.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/vibe/materialize/skill_binding.py src/vibe/materialize/changeset.py src/vibe/commands/init.py src/vibe/commands/project_plan.py src/vibe/inventory/adapters/agent_skill.py tests/materialize/test_skill_binding.py tests/commands/test_init_apply.py tests/inventory/test_agent_skill.py
git commit -m "feat: bind verified skills into project scope"
```

### Task 6: Rewrite the Bootstrap Skill around Codex conversation

**Files:**
- Modify: `bootstrap-skill/SKILL.md`
- Modify: `bootstrap-skill/agents/openai.yaml`
- Modify: `tests/skills/test_skills.py`

- [ ] **Step 1: Replace CLI-workflow assertions with conversation-native assertions**

```python
def test_bootstrap_skill_keeps_cli_internal_to_the_codex_workflow() -> None:
    document = (ROOT / "bootstrap-skill/SKILL.md").read_text(encoding="utf-8")

    assert "The user stays in the current Codex conversation" in document
    assert "Use the deterministic project capability tools internally" in document
    assert "Do not ask the user to run" in document
    assert "Do not start another Codex process" in document
    assert "Run `vibe init" not in document


def test_bootstrap_metadata_declares_internal_vibe_dependency() -> None:
    metadata = yaml.safe_load(
        (ROOT / "bootstrap-skill/agents/openai.yaml").read_text(encoding="utf-8")
    )

    assert metadata["policy"]["allow_implicit_invocation"] is True
    assert metadata["dependencies"]["tools"][0]["value"] == "vibe"
```

Codex Skill metadata currently documents MCP tool dependencies but not local CLI dependencies. Keep `agents/openai.yaml` limited to `interface` and `policy`; declare the internal `vibe` executable requirement in `SKILL.md` prose. Replace the second test above with:

```python
def test_bootstrap_skill_declares_internal_vibe_dependency_in_prose() -> None:
    document = (ROOT / "bootstrap-skill/SKILL.md").read_text(encoding="utf-8")

    assert "The internal `vibe` executable must be available" in document
    assert "Do not ask the user to run `vibe` commands" in document
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run pytest tests/skills/test_skills.py -q
```

Expected: old CLI-sequencing assertions or new conversation assertions fail.

- [ ] **Step 3: Rewrite the Skill workflow**

The Skill must instruct Codex to:

1. Keep the user in the current conversation.
2. Inspect and model the project using internal deterministic interfaces.
3. Ask only questions not answerable from the repository.
4. Present capability needs and gaps in ordinary language.
5. Request approval before project-local installation.
6. Apply and verify configuration internally.
7. Explain that ordinary future tasks use Codex-native Skill discovery.
8. Never start a second Codex process.

- [ ] **Step 4: Run Skill validation and E2E initialization tests**

Run:

```bash
uv run pytest tests/skills/test_skills.py tests/e2e/test_conversational_init.py tests/e2e/test_init.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bootstrap-skill/SKILL.md bootstrap-skill/agents/openai.yaml tests/skills/test_skills.py
git commit -m "feat: make bootstrap experience conversation native"
```

### Task 7: Add project Hook rendering and deterministic trust governance

**Files:**
- Create: `src/vibe/materialize/project_hooks.py`
- Modify: `src/vibe/inventory/adapters/codex_hook.py`
- Modify: `src/vibe/materialize/templates.py`
- Modify: `src/vibe/doctor/checks.py`
- Create: `tests/materialize/test_project_hooks.py`
- Modify: `tests/inventory/test_codex_hook.py`
- Modify: `tests/doctor/test_checks.py`

- [ ] **Step 1: Write failing Hook rendering tests**

```python
def test_renders_only_approved_project_hook_events() -> None:
    policy = ProjectHookPolicy(
        enabled_events=("PreToolUse", "PermissionRequest", "PostToolUse", "Stop"),
        command="python3 .ai-project/hooks/governance.py",
    )

    rendered = render_project_hooks(policy)
    payload = json.loads(rendered.hooks_json)

    assert set(payload["hooks"]) == {
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "Stop",
    }
    assert "UserPromptSubmit" not in payload["hooks"]


def test_hook_lock_digest_changes_when_definition_changes() -> None:
    first = render_project_hooks(ProjectHookPolicy(command="python3 a.py"))
    second = render_project_hooks(ProjectHookPolicy(command="python3 b.py"))

    assert first.content_digest != second.content_digest
```

- [ ] **Step 2: Write failing Doctor drift tests**

Add cases where `.codex/hooks.json` differs from the lock digest and where an untrusted project Hook is present. Expected severity is security-class drift, not a normal formatting warning.

- [ ] **Step 3: Verify the tests fail**

Run:

```bash
uv run pytest tests/materialize/test_project_hooks.py tests/inventory/test_codex_hook.py tests/doctor/test_checks.py -q
```

Expected: missing project Hook renderer and trust checks.

- [ ] **Step 4: Implement narrow Hook policy models and rendering**

```python
class ProjectHookPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled_events: tuple[Literal[
        "UserPromptSubmit",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "Stop",
    ], ...] = ()
    command: str = Field(min_length=1)
    approved: bool = False
```

Rendering rules:

1. Emit no Hook files unless `approved=True`.
2. Use exact events from policy; never silently add semantic routing.
3. Record the Hook JSON digest and approval provenance in the lock.
4. Treat changed definitions as requiring renewed trust.
5. Keep command handlers project-relative and reject path traversal.

- [ ] **Step 5: Extend Hook inventory to project `.codex/hooks.json`**

`CodexHookAdapter` currently discovers plugin Hook metadata. Add explicit roots or Hook-file locators so project Hooks are inventoried with `CapabilityScope.PROJECT`. Preserve plugin discovery.

- [ ] **Step 6: Extend Doctor**

Doctor must report:

- hook file missing;
- content digest mismatch;
- declared command missing;
- approval/trust record absent;
- permissions widened;
- Hook present in an untrusted project state.

- [ ] **Step 7: Run Hook, Doctor, and security tests**

Run:

```bash
uv run pytest tests/materialize/test_project_hooks.py tests/inventory/test_codex_hook.py tests/doctor/test_checks.py tests/validation/test_security_gates.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/vibe/materialize/project_hooks.py src/vibe/materialize/templates.py src/vibe/inventory/adapters/codex_hook.py src/vibe/doctor/checks.py tests/materialize/test_project_hooks.py tests/inventory/test_codex_hook.py tests/doctor/test_checks.py
git commit -m "feat: govern trusted project Codex hooks"
```

### Task 8: Deprecate external task execution as the product entry point

**Files:**
- Modify: `src/vibe/commands/run.py`
- Modify: `src/vibe/commands/plan.py`
- Modify: `src/vibe/cli.py`
- Modify: `tests/commands/test_run.py`
- Modify: `tests/commands/test_plan.py`
- Create: `docs/migration/codex-native-capability-governance.md`

- [ ] **Step 1: Write failing help and warning tests**

```python
def test_run_help_marks_command_as_compatibility_only() -> None:
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "deprecated" in result.stdout.lower()
    assert "normal Codex conversation" in result.stdout


def test_plan_help_points_to_codex_native_skill_selection() -> None:
    result = runner.invoke(app, ["plan", "--help"])

    assert result.exit_code == 0
    assert "compatibility" in result.stdout.lower()
    assert "Codex-native Skill" in result.stdout
```

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
uv run pytest tests/commands/test_run.py tests/commands/test_plan.py -q
```

Expected: help text does not contain migration guidance.

- [ ] **Step 3: Add compatibility-only help and runtime warnings**

Keep behavior unchanged in this task. Update docstrings and emit one warning before execution:

```python
typer.echo(
    "Deprecated: normal project work should continue in the current Codex conversation "
    "using Codex-native Skills. This command remains for compatibility and diagnostics.",
    err=True,
)
```

Do not remove commands until the new E2E acceptance tests pass in a released version.

- [ ] **Step 4: Write the migration guide**

The guide must cover:

- old `vibe run` and `vibe plan` flow;
- new conversation-native flow;
- why Codex owns Skill selection;
- how missing capabilities trigger `project-capability-manager`;
- how CI and diagnostics may continue using CLI commands;
- compatibility period and removal criteria.

- [ ] **Step 5: Run CLI tests**

Run:

```bash
uv run pytest tests/test_cli.py tests/commands/test_run.py tests/commands/test_plan.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/vibe/commands/run.py src/vibe/commands/plan.py src/vibe/cli.py tests/commands/test_run.py tests/commands/test_plan.py docs/migration/codex-native-capability-governance.md
git commit -m "docs: deprecate external Codex task execution flow"
```

### Task 9: Add end-to-end Codex-native project experience acceptance

**Files:**
- Create: `tests/e2e/test_codex_native_project_experience.py`
- Create: `tests/e2e/codex_native_fixture.py`
- Modify: `tests/fakes/fake_app_server.py`
- Modify: `docs/evaluation/acceptance-matrix.md`
- Modify: `docs/release-checklist.md`
- Modify: `tests/validation/test_matrix.py`

- [ ] **Step 1: Write failing E2E acceptance tests**

Add tests with these exact node IDs and observable assertions:

```python
def test_init_generates_codex_native_discoverable_project_capabilities(
    native_project: CodexNativeProjectFixture,
) -> None:
    result = native_project.initialize(selected_skill="systematic-debugging")

    assert result.exit_code == 0
    assert (native_project.root / ".agents/skills/project-capability-manager/SKILL.md").is_file()
    assert (native_project.root / ".agents/skills/systematic-debugging/SKILL.md").is_file()
    agents = (native_project.root / "AGENTS.md").read_text(encoding="utf-8")
    assert "vibe run" not in agents


def test_missing_capability_install_stays_in_current_codex_conversation(
    native_project: CodexNativeProjectFixture,
) -> None:
    session = native_project.start_session()
    original_thread_id = session.thread_id

    session.request("Validate the browser checkout flow")
    session.approve_project_candidate("browser-testing")

    assert session.thread_id == original_thread_id
    assert session.started_nested_codex_processes == 0
    assert (native_project.root / ".agents/skills/browser-testing/SKILL.md").is_file()


def test_sufficient_existing_capabilities_do_not_invoke_vibe_task_router(
    native_project: CodexNativeProjectFixture,
) -> None:
    native_project.initialize(selected_skill="systematic-debugging")
    session = native_project.start_session()

    session.request("Fix the intermittent login failure")

    assert session.loaded_skill_names == ("systematic-debugging",)
    assert "route-task" not in session.internal_commands
    assert session.started_nested_codex_processes == 0
```

Define `CodexNativeProjectFixture` in `tests/e2e/codex_native_fixture.py` and add that file to this task. It must wrap the existing fake app-server transport, expose the fields used above, and fail if a second app-server task process is started.

The fake Codex surface must model native Skill discovery inputs and record process/thread starts. It must not fake success by directly returning Vibe's expected capability choice.

- [ ] **Step 2: Verify E2E tests fail**

Run:

```bash
uv run pytest tests/e2e/test_codex_native_project_experience.py -q
```

Expected: generated files, native discovery simulation, and no-nested-process assertions fail.

- [ ] **Step 3: Extend the fake host at the correct boundary**

The fake should:

1. Load generated `AGENTS.md` and repo Skill metadata.
2. Match a small deterministic set of prompts to Skill descriptions solely for acceptance plumbing.
3. Record which `SKILL.md` files would be loaded.
4. Record app-server process and thread starts.
5. Allow the capability manager to invoke installation internally without starting another task thread.

Keep task-selection quality evaluation separate and require real Codex smoke tests in the release checklist.

- [ ] **Step 4: Replace acceptance matrix expectations**

Add expectations:

- `NATIVE-01`: initialized repo Skills are discoverable by Codex-native paths;
- `NATIVE-02`: normal task handling does not require a Vibe router call;
- `NATIVE-03`: capability gaps are resolved project-locally after approval;
- `NATIVE-04`: no nested Codex task process or thread is started;
- `NATIVE-05`: Hook governance remains deterministic and optional.

Retain security, remote provenance, update, audit, reconciliation, and organization-policy expectations.

- [ ] **Step 5: Update the release checklist**

Add an attended real-Codex smoke test:

```text
1. Initialize a fixture project from a Codex conversation.
2. Start a new Codex session in the initialized repo.
3. Ask for a bug fix that matches an installed debugging Skill.
4. Confirm Codex implicitly loads that Skill.
5. Ask for a task with a missing capability.
6. Approve a project-local candidate and confirm the original conversation continues.
7. Confirm no user-entered vibe command and no nested Codex process/thread.
```

- [ ] **Step 6: Run acceptance tests**

Run:

```bash
uv run pytest tests/e2e/test_codex_native_project_experience.py tests/validation/test_matrix.py -q
uv run pytest -m validation
```

Expected: PASS and an updated `tests/results/validation-summary.json` with all native expectations mapped.

- [ ] **Step 7: Commit**

```bash
git add tests/e2e/test_codex_native_project_experience.py tests/fakes/fake_app_server.py docs/evaluation/acceptance-matrix.md docs/release-checklist.md tests/validation/test_matrix.py tests/results/validation-summary.json
git commit -m "test: validate Codex-native capability experience"
```

### Task 10: Full verification and release evidence

**Files:**
- Modify: `docs/evaluation/validation-rounds/README.md`
- Create: `docs/evaluation/validation-rounds/round-0002.md`
- Create: `docs/evaluation/validation-rounds/round-0002.json`

- [ ] **Step 1: Install the locked environment**

Run:

```bash
uv sync --locked --all-groups
```

Expected: dependencies install without modifying `uv.lock`.

- [ ] **Step 2: Run focused native-experience validation**

Run:

```bash
uv run pytest tests/skills tests/inventory/test_agent_skill.py tests/materialize tests/e2e/test_codex_native_project_experience.py -q
```

Expected: PASS.

- [ ] **Step 3: Run security and governance validation**

Run:

```bash
uv run pytest tests/doctor tests/remote tests/validation/test_security_gates.py -q
uv run pytest -m validation
```

Expected: PASS with zero unauthorized-install, project-boundary, Hook-trust, or digest-drift failures.

- [ ] **Step 4: Run the complete quality gate**

Run:

```bash
uv run pytest
uv run ruff check .
uv run mypy src tests
uv build
git diff --check
```

Expected: all commands PASS.

- [ ] **Step 5: Perform the attended real-Codex smoke test**

Follow the exact checklist added in Task 9 and record:

- Codex version and surface;
- initialized fixture commit;
- Skill selected and loaded;
- project-local install candidate and digest;
- confirmation that no user CLI command was entered;
- confirmation that no nested Codex task process/thread started;
- reviewer and date.

- [ ] **Step 6: Create validation round 0002**

Record each revised acceptance expectation with exact automated test node IDs and the attended smoke evidence. Set open remediation epics to zero only if every expectation passes.

- [ ] **Step 7: Verify the release gate**

Run:

```bash
uv run python scripts/validation/check_release_gate.py --rounds docs/evaluation/validation-rounds
```

Expected: `round-0002.json: release gate PASS`.

- [ ] **Step 8: Commit**

```bash
git add docs/evaluation/validation-rounds docs/release-checklist.md tests/results
git commit -m "docs: record Codex-native capability validation"
```

---

## Compatibility and removal criteria

Do not delete `vibe run`, `vibe plan`, app-server task execution, or hard-routing modules in the same release that introduces the native experience. Mark them deprecated and remove them only after:

1. At least one released version ships the conversation-native flow.
2. Real Codex smoke evidence confirms Skill discovery and gap installation.
3. No current acceptance expectation depends on external task execution.
4. Migration documentation has been published.
5. Any retained hard-routing use case has been re-scoped to deterministic high-risk tool governance rather than ordinary Skill selection.

When those conditions hold, write a separate removal spec and implementation plan. Do not mix deletion with this migration.
