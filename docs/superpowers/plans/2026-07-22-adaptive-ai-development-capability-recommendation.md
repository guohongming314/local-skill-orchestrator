# Adaptive AI Development Capability Recommendation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace template-like initialization output with evidence-driven capability recommendations, traceable permissions, adaptive questions, governed remote discovery, and a hard gate before installation review.

**Architecture:** Add a typed decision model to `Blueprint`, derive capability needs from repository evidence and preferences, and keep candidate generation separate from deterministic ranking. Introduce a review-readiness evaluator so unresolved discovery and candidate decisions cannot be mistaken for an installable ChangeSet. Preserve existing inventory, remote discovery, policy filtering, atomic writes, and Doctor behavior as lower-level services.

**Tech Stack:** Python 3.12, Pydantic, Typer, pytest, YAML practice packs, existing Codex app-server integration, existing remote discovery adapters.

---

## File structure

- Create `src/vibe/models/decisions.py`: typed project permissions, authorization decisions, provenance, and tri-state values.
- Modify `src/vibe/models/blueprint.py`: attach the new decision model to every Blueprint.
- Modify `src/vibe/conversation/runner.py`: deterministically map high-impact answers instead of leaving permissions to model interpretation.
- Modify `src/vibe/commands/init.py`: accept typed answers, expose recommendation readiness, and stop before install review when discovery/candidate decisions remain unresolved.
- Create `src/vibe/recommendation/questions.py`: compute only questions whose answers can change needs, rankings, permissions, or scope.
- Create `src/vibe/recommendation/readiness.py`: pure state evaluator for discovery and installation review gates.
- Create `src/vibe/recommendation/search_terms.py`: expand abstract capability IDs, repository facts, and user-mentioned product names into provider-neutral discovery queries.
- Create `src/vibe/recommendation/explanations.py`: build consistent evidence-backed recommendation explanations.
- Modify `src/vibe/resolver/local.py`: replace bare gaps and fixed CodeGraph filtering with contextual recommendations and evidence explanations.
- Modify `src/vibe/remote/discovery.py` and `src/vibe/commands/init.py`: allow multiple search queries per capability while preserving per-source diagnostics.
- Modify `src/vibe/materialize/templates.py`: persist typed permissions, recommendation state, and decision provenance.
- Modify `src/vibe/doctor/checks.py`: report unknown high-impact permissions, unresolved required capabilities, stale discovery, and decision drift.
- Modify `bootstrap-skill/SKILL.md`: require adaptive recommendations and readiness checks before ChangeSet approval.
- Add focused tests under `tests/models`, `tests/conversation`, `tests/recommendation`, `tests/resolver`, `tests/commands`, `tests/doctor`, and `tests/e2e`.

### Task 1: Model permissions and authorizations explicitly

**Files:**
- Create: `src/vibe/models/decisions.py`
- Modify: `src/vibe/models/blueprint.py`
- Test: `tests/models/test_decisions.py`
- Test: `tests/conversation/test_structured_result.py`

- [ ] **Step 1: Write failing model tests**

```python
# tests/models/test_decisions.py
from vibe.models.blueprint import Blueprint
from vibe.models.decisions import (
    AuthorizationState,
    DecisionProvenance,
    DecisionSource,
    NetworkPolicy,
    ProjectDecisions,
    TriState,
)


def test_blueprint_defaults_unknown_permissions_without_inventing_denials() -> None:
    blueprint = Blueprint(
        project_name="web",
        goal="Build a web application",
        lifecycle_stage="active-development",
        risk_level="medium",
        repository_digest="01234567",
    )

    assert blueprint.decisions.write_project.value is TriState.UNKNOWN
    assert blueprint.decisions.execute_command.value is TriState.UNKNOWN
    assert blueprint.decisions.network_policy.value is NetworkPolicy.UNKNOWN
    assert blueprint.decisions.discovery_approval is AuthorizationState.NOT_REQUESTED


def test_permission_decision_preserves_user_provenance() -> None:
    decisions = ProjectDecisions.model_validate(
        {
            "write_project": {
                "value": "allowed",
                "provenance": {
                    "source": "user-response",
                    "reference": "permissions.write_project",
                },
            }
        }
    )

    assert decisions.write_project.value is TriState.ALLOWED
    assert decisions.write_project.provenance == DecisionProvenance(
        source=DecisionSource.USER_RESPONSE,
        reference="permissions.write_project",
    )
```

Append to `tests/conversation/test_structured_result.py`:

```python
def test_missing_network_answer_remains_unknown() -> None:
    result = parse_structured_result(valid_payload())

    assert result.blueprint.decisions.network_policy.value == "unknown"
    assert result.blueprint.decisions.discovery_approval == "not-requested"
```

- [ ] **Step 2: Run the tests and verify the new model is missing**

Run: `uv run pytest tests/models/test_decisions.py tests/conversation/test_structured_result.py::test_missing_network_answer_remains_unknown -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'vibe.models.decisions'`.

- [ ] **Step 3: Implement the typed decision model**

```python
# src/vibe/models/decisions.py
from enum import StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel


class TriState(StrEnum):
    UNKNOWN = "unknown"
    ALLOWED = "allowed"
    DENIED = "denied"


class NetworkPolicy(StrEnum):
    UNKNOWN = "unknown"
    DENIED = "denied"
    ALLOWED_READONLY = "allowed-readonly"
    ALLOWED = "allowed"


class AuthorizationState(StrEnum):
    NOT_REQUESTED = "not-requested"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class RuntimeNetwork(StrEnum):
    NONE = "none"
    READONLY = "readonly"
    READWRITE = "readwrite"
    UNKNOWN = "unknown"


class DecisionSource(StrEnum):
    UNKNOWN = "unknown"
    REPOSITORY = "repository-evidence"
    USER_RESPONSE = "user-response"
    RECOMMENDED_DEFAULT = "recommended-default"
    MIGRATION = "migration"


class DecisionProvenance(VersionedModel):
    source: DecisionSource = DecisionSource.UNKNOWN
    reference: str = Field(default="unresolved", min_length=1)


class PermissionDecision(VersionedModel):
    value: TriState = TriState.UNKNOWN
    provenance: DecisionProvenance = Field(default_factory=DecisionProvenance)


class NetworkDecision(VersionedModel):
    value: NetworkPolicy = NetworkPolicy.UNKNOWN
    provenance: DecisionProvenance = Field(default_factory=DecisionProvenance)


class ProjectDecisions(VersionedModel):
    read_project: PermissionDecision = Field(default_factory=PermissionDecision)
    write_project: PermissionDecision = Field(default_factory=PermissionDecision)
    execute_command: PermissionDecision = Field(default_factory=PermissionDecision)
    write_outside_project: PermissionDecision = Field(default_factory=PermissionDecision)
    access_secrets: PermissionDecision = Field(default_factory=PermissionDecision)
    network_policy: NetworkDecision = Field(default_factory=NetworkDecision)
    discovery_approval: AuthorizationState = AuthorizationState.NOT_REQUESTED
    artifact_fetch_approval: AuthorizationState = AuthorizationState.NOT_REQUESTED
    candidate_runtime_network: RuntimeNetwork = RuntimeNetwork.UNKNOWN
```

Add to `Blueprint`:

```python
from vibe.models.decisions import ProjectDecisions


class Blueprint(VersionedModel):
    # existing fields remain unchanged
    decisions: ProjectDecisions = Field(default_factory=ProjectDecisions)
```

- [ ] **Step 4: Run focused and model tests**

Run: `uv run pytest tests/models/test_decisions.py tests/conversation/test_structured_result.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/models/decisions.py src/vibe/models/blueprint.py tests/models/test_decisions.py tests/conversation/test_structured_result.py
git commit -m "feat: model project capability decisions"
```

### Task 2: Map interview answers deterministically

**Files:**
- Modify: `src/vibe/conversation/runner.py`
- Modify: `src/vibe/commands/init.py`
- Test: `tests/conversation/test_runner.py`
- Test: `tests/commands/test_init_model_only.py`

- [ ] **Step 1: Write failing answer-mapping tests**

```python
# tests/conversation/test_runner.py
def test_reconcile_maps_network_answer_to_typed_decision() -> None:
    result = structured_result()

    reconciled = _reconcile_answers(
        result,
        {"permissions.network": "Only read-only discovery when I approve it"},
        {"permissions.network": FieldProvenance.USER_RESPONSE},
        set(),
    )

    decision = reconciled.blueprint.decisions.network_policy
    assert decision.value == "allowed-readonly"
    assert decision.provenance.source == "user-response"
    assert decision.provenance.reference == "permissions.network"
    assert reconciled.blueprint.decisions.discovery_approval == "not-requested"


def test_reconcile_does_not_treat_interview_sandbox_as_project_policy() -> None:
    result = structured_result()

    reconciled = _reconcile_answers(result, {}, {}, set())

    assert reconciled.blueprint.decisions.network_policy.value == "unknown"
```

Add to `tests/commands/test_init_model_only.py`:

```python
def test_answer_file_maps_explicit_permissions_without_model_inference(tmp_path: Path) -> None:
    payload = run_model_only(
        tmp_path,
        answers={
            "goal": "Build a web app",
            "lifecycle_stage": "active-development",
            "risk_level": "medium",
            "permissions": {
                "write_project": "allowed",
                "execute_command": "allowed",
                "network_policy": "unknown",
            },
        },
    )

    assert payload["blueprint"]["decisions"]["write_project"]["value"] == "allowed"
    assert payload["blueprint"]["decisions"]["network_policy"]["value"] == "unknown"
```

- [ ] **Step 2: Run tests and verify permission answers are ignored**

Run: `uv run pytest tests/conversation/test_runner.py::test_reconcile_maps_network_answer_to_typed_decision tests/commands/test_init_model_only.py::test_answer_file_maps_explicit_permissions_without_model_inference -q`

Expected: FAIL because `_reconcile_answers` only maps goal, lifecycle, and risk, and `_build_structured` drops `permissions`.

- [ ] **Step 3: Add deterministic parsers and reconciliation**

Add to `src/vibe/conversation/runner.py`:

```python
from vibe.models.decisions import (
    DecisionProvenance,
    DecisionSource,
    NetworkDecision,
    NetworkPolicy,
    PermissionDecision,
    TriState,
)


def _permission_value(answer: str) -> TriState:
    normalized = answer.casefold()
    if any(token in normalized for token in ("no", "deny", "not allowed", "不允许", "禁止")):
        return TriState.DENIED
    if any(token in normalized for token in ("yes", "allow", "允许", "可以")):
        return TriState.ALLOWED
    return TriState.UNKNOWN


def _network_value(answer: str) -> NetworkPolicy:
    normalized = answer.casefold()
    if any(token in normalized for token in ("no", "deny", "not allowed", "不允许", "禁止")):
        return NetworkPolicy.DENIED
    if any(token in normalized for token in ("read-only", "readonly", "只读")):
        return NetworkPolicy.ALLOWED_READONLY
    if any(token in normalized for token in ("yes", "allow", "允许", "可以")):
        return NetworkPolicy.ALLOWED
    return NetworkPolicy.UNKNOWN


def _decision_source(provenance: FieldProvenance) -> DecisionSource:
    if provenance is FieldProvenance.RECOMMENDED_DEFAULT:
        return DecisionSource.RECOMMENDED_DEFAULT
    return DecisionSource.USER_RESPONSE
```

Inside `_reconcile_answers`, before returning, update `blueprint.decisions` for `permissions.write_project`, `permissions.execute_command`, and `permissions.network` using `model_copy`. Use `DecisionProvenance(reference=question_id, source=_decision_source(...))`; never change `discovery_approval` from an interview permission answer.

In `_build_structured`, parse the answer-file `permissions` object into the same `ProjectDecisions` structure and include it as `blueprint_payload["decisions"]`.

- [ ] **Step 4: Run conversation and command tests**

Run: `uv run pytest tests/conversation tests/commands/test_init_model_only.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/conversation/runner.py src/vibe/commands/init.py tests/conversation/test_runner.py tests/commands/test_init_model_only.py
git commit -m "fix: preserve explicit capability permissions"
```

### Task 3: Ask only recommendation-changing questions

**Files:**
- Create: `src/vibe/recommendation/__init__.py`
- Create: `src/vibe/recommendation/questions.py`
- Modify: `src/vibe/conversation/interview.py`
- Test: `tests/recommendation/test_questions.py`
- Test: `tests/conversation/test_interview.py`

- [ ] **Step 1: Write failing adaptive-question tests**

```python
# tests/recommendation/test_questions.py
from vibe.recommendation.questions import RecommendationQuestionContext, adaptive_questions


def test_existing_playwright_only_asks_about_interactive_debugging() -> None:
    context = RecommendationQuestionContext(
        requirements=("browser.validation",),
        local_capabilities=("cli.playwright",),
        repository_facts={"project_type": "web-application"},
        unknown_decisions=frozenset({"browser.interactive-debugging"}),
    )

    questions = adaptive_questions(context)

    assert [item.question_id for item in questions] == ["browser.interactive-debugging"]
    assert "Chrome DevTools" not in questions[0].text
    assert "interactive" in questions[0].impact.casefold()


def test_memory_question_is_omitted_for_short_lived_exploration() -> None:
    context = RecommendationQuestionContext(
        requirements=("project.continuity-memory",),
        local_capabilities=(),
        repository_facts={"lifecycle_stage": "exploration"},
        unknown_decisions=frozenset({"memory.persistence"}),
    )

    assert adaptive_questions(context) == ()
```

- [ ] **Step 2: Run tests and verify the recommendation package is missing**

Run: `uv run pytest tests/recommendation/test_questions.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'vibe.recommendation'`.

- [ ] **Step 3: Implement pure question selection**

```python
# src/vibe/recommendation/questions.py
from dataclasses import dataclass
from typing import Mapping

from vibe.conversation.interview import InterviewQuestion


@dataclass(frozen=True)
class RecommendationQuestionContext:
    requirements: tuple[str, ...]
    local_capabilities: tuple[str, ...]
    repository_facts: Mapping[str, object]
    unknown_decisions: frozenset[str]


@dataclass(frozen=True)
class AdaptiveQuestion:
    question_id: str
    text: str
    impact: str


def adaptive_questions(context: RecommendationQuestionContext) -> tuple[AdaptiveQuestion, ...]:
    questions: list[AdaptiveQuestion] = []
    if (
        "browser.validation" in context.requirements
        and "cli.playwright" in context.local_capabilities
        and "browser.interactive-debugging" in context.unknown_decisions
    ):
        questions.append(
            AdaptiveQuestion(
                question_id="browser.interactive-debugging",
                text="Do you also need interactive browser debugging in addition to repeatable browser tests?",
                impact="A yes answer adds interactive browser-control candidates; otherwise the existing test runner remains preferred.",
            )
        )
    if (
        "project.continuity-memory" in context.requirements
        and context.repository_facts.get("lifecycle_stage") != "exploration"
        and "memory.persistence" in context.unknown_decisions
    ):
        questions.append(
            AdaptiveQuestion(
                question_id="memory.persistence",
                text="Should project context persist across Codex sessions?",
                impact="A yes answer enables persistent-memory candidates and requires a storage-boundary decision.",
            )
        )
    return tuple(questions)
```

Expose adaptive questions from `src/vibe/recommendation/__init__.py`. Extend `InterviewQuestion` with `impact: str | None = None`, and append converted adaptive questions after the repository-unknown interview questions without changing the stable order of existing questions.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/recommendation/test_questions.py tests/conversation/test_interview.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/recommendation src/vibe/conversation/interview.py tests/recommendation/test_questions.py tests/conversation/test_interview.py
git commit -m "feat: ask recommendation-changing questions"
```

### Task 4: Expand the development-loop capability model and remove bare gaps

**Files:**
- Create: `practice-packs/development-design/pack.yaml`
- Create: `practice-packs/code-optimization/pack.yaml`
- Modify: `practice-packs/base-engineering/pack.yaml`
- Modify: `src/vibe/resolver/local.py`
- Modify: `src/vibe/inventory/data/provider-taxonomy.v1.json`
- Test: `tests/resolver/test_local.py`
- Test: `tests/e2e/test_capability_domains.py`

- [ ] **Step 1: Write failing gap recommendation tests**

```python
# tests/resolver/test_local.py
def test_base_engineering_gaps_always_include_actionable_candidate_directions() -> None:
    plan = resolve_for(requirements=(
        requirement("repository.exploration"),
        requirement("quality.gates"),
        requirement("development.design"),
        requirement("code.optimization"),
    ))

    gaps = {item.requirement: item for item in plan.resolutions if item.status == "gap"}
    assert set(gaps) == {
        "repository.exploration",
        "quality.gates",
        "development.design",
        "code.optimization",
    }
    assert all(item.recommendation and item.recommendation.candidates for item in gaps.values())
    assert gaps["development.design"].recommendation.candidates[0].provider == "workflow-design"
    assert gaps["code.optimization"].recommendation.candidates[0].provider == "project-native-analysis"
```

Extend `tests/e2e/test_capability_domains.py` so a blank active-development web project asserts that the four capability domains appear and none is a bare gap.

- [ ] **Step 2: Run tests and verify bare gaps remain**

Run: `uv run pytest tests/resolver/test_local.py::test_base_engineering_gaps_always_include_actionable_candidate_directions tests/e2e/test_capability_domains.py -q`

Expected: FAIL because the new requirements do not exist and `quality.gates` / `repository.exploration` return `recommendation=None`.

- [ ] **Step 3: Add capability requirements and provider-neutral leads**

Create `practice-packs/development-design/pack.yaml`:

```yaml
schema_version: '1'
pack_id: development-design
name: Development Design
description: Evidence-driven design and implementation planning
priority: 90
match:
  all_of:
    - field: lifecycle_stage
      operator: in
      value: [active-development, maintenance, production]
requirements:
  - requirement_id: development-design
    capability: development.design
    strength: recommended
    rationale: Compare implementation approaches before changing behavior
    verification:
      - Record the selected approach and verification strategy
```

Create `practice-packs/code-optimization/pack.yaml` with capability `code.optimization`, recommended strength, and verification requiring project-native static analysis and focused performance evidence.

Replace the entries for `quality.gates` and `repository.exploration` in `_NO_DEFAULT_RECOMMENDATIONS` with `_LOCAL_GAP_RECOMMENDATIONS` entries:

```python
"repository.exploration": (
    RecommendationCandidate(
        kind=CapabilityKind.SKILL,
        provider="project-native-exploration",
        permissions=(Permission.READ_PROJECT,),
        why="Start with repository-native search, manifests, language metadata, and verified local indexes; remotely discover an additional provider only when those are insufficient.",
        strength=RequirementStrength.REQUIRED,
    ),
),
"quality.gates": (
    RecommendationCandidate(
        kind=CapabilityKind.CLI_TOOL,
        provider="project-native-quality",
        permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        why="Compose the repository's existing formatter, linter, type checker, tests, and security checks before adding another quality product.",
        strength=RequirementStrength.REQUIRED,
    ),
),
"development.design": (
    RecommendationCandidate(
        kind=CapabilityKind.SKILL,
        provider="workflow-design",
        permissions=(Permission.READ_PROJECT,),
        why="Discover a design workflow that compares approaches and produces a testable implementation plan; installed providers such as Superpowers compete here.",
        strength=RequirementStrength.RECOMMENDED,
    ),
),
"code.optimization": (
    RecommendationCandidate(
        kind=CapabilityKind.SKILL,
        provider="project-native-analysis",
        permissions=(Permission.READ_PROJECT, Permission.EXECUTE_COMMAND),
        why="Prefer language- and framework-aware analysis backed by repository measurements; use user-mentioned optimization products as discovery leads.",
        strength=RequirementStrength.RECOMMENDED,
    ),
),
```

Add taxonomy aliases for installed providers that declare `development.design` or `code.optimization`; do not map a product name unless its inspected manifest proves the capability.

- [ ] **Step 4: Run resolver and capability-domain tests**

Run: `uv run pytest tests/resolver/test_local.py tests/e2e/test_capability_domains.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add practice-packs src/vibe/resolver/local.py src/vibe/inventory/data/provider-taxonomy.v1.json tests/resolver/test_local.py tests/e2e/test_capability_domains.py
git commit -m "feat: model the AI development capability loop"
```

### Task 5: Make CodeGraph, memory, and browser recommendations contextual

**Files:**
- Create: `src/vibe/recommendation/context.py`
- Modify: `src/vibe/resolver/local.py`
- Test: `tests/recommendation/test_context.py`
- Test: `tests/resolver/test_local.py`

- [ ] **Step 1: Write failing context tests**

```python
# tests/recommendation/test_context.py
from vibe.recommendation.context import codegraph_value, memory_value


def test_codegraph_is_valuable_for_complex_cross_module_repository() -> None:
    result = codegraph_value(
        {
            "repository_size": "medium",
            "module_count": 42,
            "language_count": 3,
            "cross_module_changes": "frequent",
            "local_symbol_index": False,
        }
    )

    assert result.recommended is True
    assert "cross-module" in " ".join(result.reasons)


def test_large_simple_repository_can_defer_codegraph() -> None:
    result = codegraph_value(
        {
            "repository_size": "large",
            "module_count": 4,
            "language_count": 1,
            "cross_module_changes": "rare",
            "local_symbol_index": True,
        }
    )

    assert result.recommended is False


def test_memory_is_deferred_when_persistence_is_denied() -> None:
    result = memory_value(
        {"lifecycle_stage": "production", "memory.persistence": "denied"}
    )

    assert result.recommended is False
    assert "denied" in result.reasons
```

- [ ] **Step 2: Run tests and verify the context evaluator is missing**

Run: `uv run pytest tests/recommendation/test_context.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement deterministic context value evaluation**

```python
# src/vibe/recommendation/context.py
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ContextValue:
    recommended: bool
    score: int
    reasons: tuple[str, ...]


def codegraph_value(facts: Mapping[str, object]) -> ContextValue:
    score = 0
    reasons: list[str] = []
    if int(facts.get("module_count", 0)) >= 20:
        score += 2
        reasons.append("many modules increase navigation cost")
    if int(facts.get("language_count", 0)) >= 2:
        score += 2
        reasons.append("multiple languages weaken a single language-server view")
    if facts.get("cross_module_changes") == "frequent":
        score += 3
        reasons.append("frequent cross-module changes need impact analysis")
    if facts.get("local_symbol_index") is True:
        score -= 3
        reasons.append("an existing local symbol index already covers navigation")
    return ContextValue(score >= 3, score, tuple(reasons))


def memory_value(facts: Mapping[str, object]) -> ContextValue:
    if facts.get("memory.persistence") == "denied":
        return ContextValue(False, -10, ("persistent memory was denied",))
    if facts.get("lifecycle_stage") == "exploration":
        return ContextValue(False, -2, ("short-lived exploration has low persistence value",))
    return ContextValue(True, 2, ("longer-lived work benefits from durable decisions",))
```

Replace `_is_large_monorepo` gating in `_contextual_filter` with these evaluators. For browser candidates, prefer existing deterministic test runners for `browser.validation`; only rank interactive MCP candidates highly when the adaptive answer `browser.interactive-debugging` is allowed.

- [ ] **Step 4: Run context and resolver tests**

Run: `uv run pytest tests/recommendation/test_context.py tests/resolver/test_local.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/recommendation/context.py src/vibe/resolver/local.py tests/recommendation/test_context.py tests/resolver/test_local.py
git commit -m "feat: rank conditional development capabilities"
```

### Task 6: Expand discovery queries without hard-coding a product bundle

**Files:**
- Create: `src/vibe/recommendation/search_terms.py`
- Modify: `src/vibe/remote/discovery.py`
- Modify: `src/vibe/commands/init.py`
- Test: `tests/recommendation/test_search_terms.py`
- Test: `tests/remote/test_discovery.py`

- [ ] **Step 1: Write failing query-expansion tests**

```python
# tests/recommendation/test_search_terms.py
from vibe.recommendation.search_terms import DiscoveryQueryContext, discovery_queries


def test_queries_combine_capability_repository_and_user_product_leads() -> None:
    context = DiscoveryQueryContext(
        capability="code.optimization",
        languages=("python", "typescript"),
        frameworks=("fastapi", "react"),
        user_product_leads=("Ponytail",),
    )

    queries = discovery_queries(context)

    assert queries[0] == "code.optimization"
    assert "python typescript code optimization refactoring static analysis" in queries
    assert "Ponytail code optimization" in queries


def test_unknown_product_lead_is_preserved_without_becoming_verified_identity() -> None:
    queries = discovery_queries(
        DiscoveryQueryContext(
            capability="development.design",
            user_product_leads=("supperpowers",),
        )
    )

    assert "supperpowers development design" in queries
```

- [ ] **Step 2: Run tests and verify query expansion is missing**

Run: `uv run pytest tests/recommendation/test_search_terms.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement deterministic query expansion**

```python
# src/vibe/recommendation/search_terms.py
from dataclasses import dataclass


_CAPABILITY_TERMS = {
    "code.optimization": ("code optimization", "refactoring", "static analysis"),
    "development.design": ("development design", "implementation planning", "architecture workflow"),
    "repository.exploration": ("repository exploration", "code search", "symbol index"),
    "quality.gates": ("quality gates", "lint typecheck test security scan"),
    "project.continuity-memory": ("cross session project memory", "decision memory"),
    "browser.validation": ("browser automation", "browser testing", "interactive browser debugging"),
}


@dataclass(frozen=True)
class DiscoveryQueryContext:
    capability: str
    languages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    user_product_leads: tuple[str, ...] = ()


def discovery_queries(context: DiscoveryQueryContext) -> tuple[str, ...]:
    terms = _CAPABILITY_TERMS.get(context.capability, (context.capability,))
    queries = [context.capability]
    ecosystem = " ".join((*context.languages, *context.frameworks)).strip()
    if ecosystem:
        queries.append(f"{ecosystem} {' '.join(terms)}")
    queries.extend(f"{lead} {terms[0]}" for lead in context.user_product_leads)
    return tuple(dict.fromkeys(queries))
```

Extend `DiscoveryService.discover` to accept `queries: tuple[str, ...] | None = None`, call every approved source for every query, preserve query text in diagnostics, then reuse existing deduplication and hard filtering. Build query contexts in `_discover_remote` from repository facts, Blueprint preferences, and `preferences["product_leads"]` parsed as a comma-separated list.

- [ ] **Step 4: Run recommendation and remote tests**

Run: `uv run pytest tests/recommendation/test_search_terms.py tests/remote/test_discovery.py tests/remote/test_sources.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/recommendation/search_terms.py src/vibe/remote/discovery.py src/vibe/commands/init.py tests/recommendation/test_search_terms.py tests/remote/test_discovery.py
git commit -m "feat: search capabilities with adaptive provider leads"
```

### Task 7: Gate ChangeSet review on recommendation readiness

**Files:**
- Create: `src/vibe/recommendation/readiness.py`
- Modify: `src/vibe/commands/init.py`
- Modify: `src/vibe/workflows/state.py`
- Modify: `src/vibe/workflows/init_graph.py`
- Test: `tests/recommendation/test_readiness.py`
- Test: `tests/commands/test_init_apply.py`

- [ ] **Step 1: Write failing readiness tests**

```python
# tests/recommendation/test_readiness.py
from vibe.recommendation.readiness import ReviewReadiness, evaluate_review_readiness


def test_not_requested_discovery_blocks_install_review_for_important_gap() -> None:
    readiness = evaluate_review_readiness(
        required_gaps=("quality.gates",),
        recommended_gaps=("browser.validation",),
        discovery_status={
            "quality.gates": "not-requested",
            "browser.validation": "not-requested",
        },
        candidate_decisions={},
        unknown_permissions=("network_policy",),
    )

    assert readiness.ready is False
    assert readiness.next_action == "request-discovery-decision"
    assert "quality.gates" in readiness.blocking_requirements


def test_explicit_deferral_allows_configuration_review() -> None:
    readiness = evaluate_review_readiness(
        required_gaps=(),
        recommended_gaps=("browser.validation",),
        discovery_status={"browser.validation": "not-requested"},
        candidate_decisions={"browser.validation": "defer"},
        unknown_permissions=(),
    )

    assert readiness.ready is True
```

Add to `tests/commands/test_init_apply.py`:

```python
def test_init_does_not_offer_changeset_before_discovery_decision(tmp_path: Path) -> None:
    root = tmp_path / "adaptive-review"
    root.mkdir()
    result = invoke(root, web_answers(tmp_path), run_id="adaptive-review", dry_run=True)

    payload = json.loads(result.stdout)
    assert payload["review_readiness"]["ready"] is False
    assert payload["review_readiness"]["next_action"] == "request-discovery-decision"
    assert "dry_run_changeset" not in payload
```

- [ ] **Step 2: Run tests and verify init currently proceeds to dry-run**

Run: `uv run pytest tests/recommendation/test_readiness.py tests/commands/test_init_apply.py::test_init_does_not_offer_changeset_before_discovery_decision -q`

Expected: FAIL because readiness does not exist and `--dry-run` currently builds a ChangeSet.

- [ ] **Step 3: Implement the pure readiness evaluator**

```python
# src/vibe/recommendation/readiness.py
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ReviewReadiness:
    ready: bool
    next_action: str
    blocking_requirements: tuple[str, ...] = ()
    unknown_permissions: tuple[str, ...] = ()


def evaluate_review_readiness(
    *,
    required_gaps: tuple[str, ...],
    recommended_gaps: tuple[str, ...],
    discovery_status: Mapping[str, str],
    candidate_decisions: Mapping[str, str],
    unknown_permissions: tuple[str, ...],
) -> ReviewReadiness:
    unresolved_required = tuple(
        item
        for item in required_gaps
        if candidate_decisions.get(item) not in {"accept", "reject", "defer"}
    )
    not_requested = tuple(
        item
        for item in (*required_gaps, *recommended_gaps)
        if discovery_status.get(item) == "not-requested"
        and candidate_decisions.get(item) not in {"reject", "defer"}
    )
    if unresolved_required or not_requested:
        return ReviewReadiness(
            ready=False,
            next_action="request-discovery-decision",
            blocking_requirements=tuple(dict.fromkeys((*unresolved_required, *not_requested))),
            unknown_permissions=unknown_permissions,
        )
    return ReviewReadiness(
        ready=not unknown_permissions,
        next_action="review-installation" if not unknown_permissions else "request-permission-decision",
        unknown_permissions=unknown_permissions,
    )
```

Compute readiness after discovery reports and resolution are built. Add `review_readiness` to JSON output. If readiness is false, pause in a new `InitStage.RECOMMEND` stage and return without calling `_project_changeset`, even when `--confirm` or `--dry-run` is present. Resume only after explicit discovery and candidate decisions are supplied.

- [ ] **Step 4: Run workflow and command tests**

Run: `uv run pytest tests/recommendation/test_readiness.py tests/workflows tests/commands/test_init_apply.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/recommendation/readiness.py src/vibe/commands/init.py src/vibe/workflows/state.py src/vibe/workflows/init_graph.py tests/recommendation/test_readiness.py tests/commands/test_init_apply.py
git commit -m "feat: gate installation review on recommendations"
```

### Task 8: Persist evidence-backed recommendations and improve Doctor

**Files:**
- Create: `src/vibe/recommendation/explanations.py`
- Modify: `src/vibe/materialize/templates.py`
- Modify: `src/vibe/doctor/checks.py`
- Test: `tests/recommendation/test_explanations.py`
- Test: `tests/materialize/test_templates.py`
- Test: `tests/doctor/test_checks.py`

- [ ] **Step 1: Write failing explanation and Doctor tests**

```python
# tests/recommendation/test_explanations.py
from vibe.recommendation.explanations import RecommendationEvidence, explain_candidate


def test_candidate_explanation_covers_need_fit_permissions_and_alternative() -> None:
    explanation = explain_candidate(
        RecommendationEvidence(
            requirement="browser.validation",
            provider="playwright",
            need_reason="The repository contains a browser-facing application.",
            fit_reasons=("Playwright configuration already exists",),
            permissions=("read-project", "execute-command"),
            verification="verified-local",
            alternative="chrome-devtools",
            alternative_reason="better for interactive debugging but requires networked MCP runtime",
        )
    )

    assert "browser-facing" in explanation
    assert "read-project" in explanation
    assert "verified-local" in explanation
    assert "chrome-devtools" in explanation
```

Append to `tests/doctor/test_checks.py`:

```python
def test_doctor_reports_unknown_network_policy_and_unresolved_required_gap(tmp_path: Path) -> None:
    write_initialized_project(
        tmp_path,
        decisions={"network_policy": {"value": "unknown"}},
        unresolved_required=("quality.gates",),
    )

    findings = run_checks(tmp_path)

    assert any(item.code == "unknown-capability-permission" for item in findings)
    assert any(item.code == "unresolved-required-capability" for item in findings)
```

- [ ] **Step 2: Run tests and verify evidence rendering is missing**

Run: `uv run pytest tests/recommendation/test_explanations.py tests/doctor/test_checks.py::test_doctor_reports_unknown_network_policy_and_unresolved_required_gap -q`

Expected: FAIL because the explanation module and Doctor findings do not exist.

- [ ] **Step 3: Implement explanation rendering and persisted state**

```python
# src/vibe/recommendation/explanations.py
from dataclasses import dataclass


@dataclass(frozen=True)
class RecommendationEvidence:
    requirement: str
    provider: str
    need_reason: str
    fit_reasons: tuple[str, ...]
    permissions: tuple[str, ...]
    verification: str
    alternative: str
    alternative_reason: str


def explain_candidate(evidence: RecommendationEvidence) -> str:
    fit = "; ".join(evidence.fit_reasons)
    permissions = ", ".join(evidence.permissions) or "none"
    return (
        f"Need: {evidence.need_reason} Provider: {evidence.provider}. "
        f"Fit: {fit}. Permissions: {permissions}. Verification: {evidence.verification}. "
        f"Alternative: {evidence.alternative} — {evidence.alternative_reason}."
    )
```

Render typed decisions and provenance into `.ai-project/blueprint.yaml`; render needs, evidence, candidate scores, discovery status, and user decisions into `.ai-project/capabilities.yaml` and `.ai-project/decisions.md`. Add Doctor checks that emit:

```python
DoctorFinding(
    code="unknown-capability-permission",
    severity="warning",
    message="network_policy remains unknown; request a user decision before networked discovery or runtime use",
)
```

and:

```python
DoctorFinding(
    code="unresolved-required-capability",
    severity="error",
    message=f"required capability remains unresolved: {capability}",
)
```

Use the existing discovery timestamps and lock identities to report `stale-discovery-evidence` and `recommendation-lock-drift` when cached evidence is expired or the selected candidate no longer matches the lock.

- [ ] **Step 4: Run recommendation, materialize, and Doctor tests**

Run: `uv run pytest tests/recommendation/test_explanations.py tests/materialize/test_templates.py tests/doctor/test_checks.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/recommendation/explanations.py src/vibe/materialize/templates.py src/vibe/doctor/checks.py tests/recommendation/test_explanations.py tests/materialize/test_templates.py tests/doctor/test_checks.py
git commit -m "feat: persist and diagnose recommendation evidence"
```

### Task 9: Govern the Bootstrap conversation and verify the complete flow

**Files:**
- Modify: `bootstrap-skill/SKILL.md`
- Modify: `tests/skills/test_skills.py`
- Create: `tests/e2e/test_adaptive_recommendation_flow.py`
- Modify: `docs/release-checklist.md`

- [ ] **Step 1: Write failing Skill contract and end-to-end tests**

```python
# tests/skills/test_skills.py
def test_bootstrap_skill_requires_adaptive_recommendations_before_changeset() -> None:
    text = BOOTSTRAP_SKILL.read_text(encoding="utf-8")

    assert "Do not infer an unanswered permission as denied" in text
    assert "Ask only when the answer can change" in text
    assert "Do not request ChangeSet approval while recommendation readiness is false" in text
```

```python
# tests/e2e/test_adaptive_recommendation_flow.py
def test_blank_web_project_recommends_then_discovers_then_reviews(tmp_path: Path) -> None:
    root = build_blank_web_project(tmp_path)

    first = init_json(root, answers=answers(network_policy="unknown"))
    assert first["review_readiness"]["ready"] is False
    assert first["review_readiness"]["next_action"] == "request-discovery-decision"
    assert first["blueprint"]["decisions"]["network_policy"]["value"] == "unknown"
    assert all(gap["recommendation"]["candidates"] for gap in important_gaps(first))

    discovered = init_json(
        root,
        resume=True,
        remote_discovery=True,
        answers=answers(network_policy="allowed-readonly"),
        remote_snapshot=adaptive_candidate_snapshot(),
    )
    assert any(
        candidate["provider"] in {"playwright", "chrome-devtools"}
        for candidate in candidates_for(discovered, "browser.validation")
    )
    assert discovered["review_readiness"]["next_action"] in {
        "request-candidate-decision",
        "review-installation",
    }

    reviewed = init_json(
        root,
        resume=True,
        candidate_decisions=accept_ranked_candidates(discovered),
        dry_run=True,
    )
    assert reviewed["review_readiness"]["ready"] is True
    assert reviewed["dry_run_changeset"]
```

- [ ] **Step 2: Run tests and verify the current conversation contract is insufficient**

Run: `uv run pytest tests/skills/test_skills.py::test_bootstrap_skill_requires_adaptive_recommendations_before_changeset tests/e2e/test_adaptive_recommendation_flow.py -q`

Expected: FAIL because the Skill lacks the exact adaptive and readiness rules and the end-to-end state transitions are not implemented.

- [ ] **Step 3: Update the Bootstrap Skill contract**

Add these rules to `bootstrap-skill/SKILL.md` after repository modeling and before remote discovery:

```markdown
- Build an evidence-backed first recommendation before asking preference questions.
- Ask only when the answer can change a capability need, candidate ranking, permission boundary, or installation scope. State that impact in the question.
- Treat user-mentioned product names as discovery leads, not preselected providers. Preserve spelling uncertainty until identity is verified.
- Do not infer an unanswered permission as denied. Distinguish project network policy, discovery approval, artifact-fetch approval, and candidate runtime network.
- Do not request ChangeSet approval while recommendation readiness is false. Resolve, explicitly reject, or explicitly defer important gaps first.
```

Update the release checklist with the full three-stage smoke test: recommendation pause, approved discovery, candidate decision, exact ChangeSet, apply, and Doctor.

- [ ] **Step 4: Run the focused end-to-end suite**

Run: `uv run pytest tests/skills/test_skills.py tests/e2e/test_adaptive_recommendation_flow.py tests/e2e/test_remote_install_loop.py tests/e2e/test_init.py -q`

Expected: PASS.

- [ ] **Step 5: Run the full verification suite**

Run: `uv run pytest -q`

Expected: PASS with no newly introduced warnings or failures.

Run: `uv run ruff check src tests`

Expected: PASS.

Run: `uv run mypy src/vibe`

Expected: PASS, or if the repository does not configure mypy, exit with the documented “command not found/config missing” prerequisite rather than weakening type checks.

- [ ] **Step 6: Commit**

```bash
git add bootstrap-skill/SKILL.md tests/skills/test_skills.py tests/e2e/test_adaptive_recommendation_flow.py docs/release-checklist.md
git commit -m "test: validate adaptive capability recommendations"
```

### Task 10: Final migration and compatibility verification

**Files:**
- Modify: `src/vibe/migrations/registry.py`
- Test: `tests/migrations/test_registry.py`
- Test: `tests/commands/test_init_apply.py`
- Test: `tests/doctor/test_checks.py`

- [ ] **Step 1: Write failing legacy-state migration tests**

```python
# tests/migrations/test_registry.py
def test_legacy_blueprint_migrates_missing_decisions_to_unknown() -> None:
    migrated = migrate_artifact(
        "blueprint",
        {
            "schema_version": "1",
            "project_name": "legacy",
            "goal": "Maintain a project",
            "lifecycle_stage": "maintenance",
            "risk_level": "medium",
            "repository_digest": "01234567",
        },
    )

    assert migrated["decisions"]["network_policy"]["value"] == "unknown"
    assert migrated["decisions"]["network_policy"]["provenance"]["source"] == "migration"
```

- [ ] **Step 2: Run the migration test and verify no migration exists**

Run: `uv run pytest tests/migrations/test_registry.py::test_legacy_blueprint_migrates_missing_decisions_to_unknown -q`

Expected: FAIL because legacy artifacts do not gain typed decision provenance.

- [ ] **Step 3: Implement explicit legacy migration**

Register a Blueprint artifact migration that inserts `ProjectDecisions` defaults and changes every default provenance source from `unknown` to `migration`, with reference `legacy-blueprint-without-decisions`. Do not derive denial from legacy summaries or missing remote-candidate caches.

- [ ] **Step 4: Run compatibility and full tests**

Run: `uv run pytest tests/migrations tests/commands/test_init_apply.py tests/doctor/test_checks.py -q`

Expected: PASS.

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vibe/migrations/registry.py tests/migrations/test_registry.py tests/commands/test_init_apply.py tests/doctor/test_checks.py
git commit -m "fix: migrate legacy recommendation decisions safely"
```
