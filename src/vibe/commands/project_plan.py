"""Deterministic local inventory and resolution planning for project initialization."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

from vibe.commands.capabilities import _default_cli_specs
from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.adapters.base import (
    AdapterDiscovery,
    AdapterProvenance,
    AdapterScanResult,
    AdapterVerification,
    CapabilityAdapter,
)
from vibe.inventory.adapters.cli_tool import CliToolAdapter
from vibe.inventory.adapters.codex_hook import CodexHookAdapter
from vibe.inventory.adapters.codex_mcp import CodexMcpAdapter
from vibe.inventory.adapters.codex_plugin import CodexPluginAdapter
from vibe.inventory.service import InventoryResult, InventoryService
from vibe.models.blueprint import Blueprint
from vibe.models.capability import (
    CapabilityKind,
    CapabilityManifest,
    CapabilityScope,
    Permission,
)
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot
from vibe.models.resolution import CapabilityResolution, ResolutionPlan, ResolutionStatus
from vibe.practices.calibration import load_confirmed_overrides
from vibe.practices.evaluator import evaluate_practice_packs
from vibe.practices.loader import load_practice_packs
from vibe.practices.models import RequirementStrength
from vibe.remote.models import RemoteCandidate
from vibe.remote.scoring import CandidateEvidence
from vibe.resolver.local import resolve_local_capabilities
from vibe.resolver.requirements import AbstractCapabilityRequirement


@dataclass(frozen=True)
class ProjectPlan:
    inventory: InventoryResult
    requirements: tuple[AbstractCapabilityRequirement, ...]
    resolution: ResolutionPlan
    repository: RepositorySnapshot


@dataclass(frozen=True)
class _MarkerSpec:
    locator: str
    capability_id: str
    name: str
    provides: tuple[str, ...]
    kind: CapabilityKind
    permissions: frozenset[Permission]


class _ProjectMarkerAdapter:
    adapter_id = "project-marker"

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._specs = {
            ".codegraph/index.json": _MarkerSpec(
                locator=".codegraph/index.json",
                capability_id="product.codegraph",
                name="CodeGraph",
                provides=("analysis.code-relationships",),
                kind=CapabilityKind.CLI_TOOL,
                permissions=frozenset({Permission.READ_PROJECT}),
            ),
            ".memory-provider.json": _MarkerSpec(
                locator=".memory-provider.json",
                capability_id="memory.local-leads",
                name="Local memory leads",
                provides=("memory.local-leads", "cross-session-memory"),
                kind=CapabilityKind.MCP,
                permissions=frozenset({Permission.READ_PROJECT}),
            ),
        }

    def discover(self) -> tuple[AdapterDiscovery, ...]:
        return tuple(
            AdapterDiscovery(locator=locator)
            for locator in sorted(self._specs)
            if (self._root / locator).is_file()
        )

    def scan(self, discovery: AdapterDiscovery) -> AdapterScanResult:
        spec = self._specs[discovery.locator]
        source = self._root / spec.locator
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        manifest = CapabilityManifest(
            capability_id=spec.capability_id,
            name=spec.name,
            kind=spec.kind,
            scope=CapabilityScope.PROJECT,
            source=spec.locator,
            provides=spec.provides,
            permissions=spec.permissions,
            content_digest=digest,
            verified=True,
        )
        return AdapterScanResult(
            manifest=manifest,
            provenance=AdapterProvenance(
                adapter_id=self.adapter_id, locator=spec.locator
            ),
            verification=AdapterVerification(
                verified=True, details=(f"marker:{spec.locator}",)
            ),
        )


class _SourceSkillAdapter(AgentSkillAdapter):
    """Ignore the generated capability Skill so repeat initialization stays stable."""

    def discover(self) -> tuple[AdapterDiscovery, ...]:
        return tuple(
            item
            for item in super().discover()
            if Path(item.locator).parent.name != "project-capability-manager"
        )


def scan_project_inventory(root: Path) -> InventoryResult:
    """Scan only deterministic project-local capability sources."""
    return _project_inventory(root)


def build_project_plan(
    root: Path,
    blueprint: Blueprint,
    repository: RepositorySnapshot,
    *,
    inventory: InventoryResult | None = None,
    remote_candidates: tuple[RemoteCandidate, ...] = (),
    remote_evidence: dict[str, CandidateEvidence] | None = None,
    rejected_remote_candidates: frozenset[str] = frozenset(),
) -> ProjectPlan:
    profiled = _with_scale_facts(repository)
    inventory = inventory or _project_inventory(root)
    requirements = _requirements(root, inventory, blueprint, profiled)
    resolution = resolve_local_capabilities(
        requirements,
        inventory,
        blueprint,
        profiled,
        remote_candidates=remote_candidates,
        remote_evidence=remote_evidence,
        rejected_remote_candidates=rejected_remote_candidates,
    )
    rejections = _load_rejections(root)
    if rejections:
        resolution = resolution.model_copy(
            update={
                "resolutions": (
                    *resolution.resolutions,
                    *(
                        CapabilityResolution(
                            requirement=capability,
                            status=ResolutionStatus.REJECTED,
                            reason="explicitly rejected by project policy",
                        )
                        for capability in rejections
                    ),
                )
            }
        )
    return ProjectPlan(inventory, requirements, resolution, profiled)


def _project_inventory(root: Path) -> InventoryResult:
    codex_home = _user_codex_home()
    skills = _SourceSkillAdapter(
        roots=(
            SkillRoot(root / ".agents" / "skills", CapabilityScope.PROJECT),
            SkillRoot(root / ".codex" / "skills", CapabilityScope.PROJECT),
            SkillRoot(Path.home() / ".agents" / "skills", CapabilityScope.USER),
            SkillRoot(codex_home / "skills", CapabilityScope.USER),
        )
    )
    plugins_root = codex_home / "plugins"
    adapters: list[CapabilityAdapter] = [
        skills,
        _ProjectMarkerAdapter(root),
        CodexPluginAdapter(roots=(plugins_root,)),
        CodexHookAdapter(roots=(plugins_root,)),
    ]
    config = codex_home / "config.toml"
    if config.is_file():
        cli_specs = tuple(
            replace(spec, scope=CapabilityScope.USER) for spec in _default_cli_specs()
        )
        adapters.extend(
            (CliToolAdapter(specs=cli_specs), CodexMcpAdapter(config=config))
        )
    return InventoryService().scan(adapters)


def _user_codex_home() -> Path:
    """Resolve user Codex state from CODEX_HOME, falling back to ~/.codex."""
    configured = os.environ.get("CODEX_HOME")
    path = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return path.resolve()


def _requirements(
    root: Path,
    inventory: InventoryResult,
    blueprint: Blueprint,
    repository: RepositorySnapshot,
) -> tuple[AbstractCapabilityRequirement, ...]:
    packs_root = Path(__file__).resolve().parents[3] / "practice-packs"
    pack_requirements = evaluate_practice_packs(
        load_practice_packs(packs_root),
        blueprint,
        repository,
        overrides=load_confirmed_overrides(root),
    )
    marker_requirements = _marker_requirements(inventory)
    return tuple(
        sorted(
            (*pack_requirements, *marker_requirements),
            key=lambda item: item.capability,
        )
    )


def _marker_requirements(
    inventory: InventoryResult,
) -> tuple[AbstractCapabilityRequirement, ...]:
    capabilities = sorted(
        {
            provided
            for item in inventory.capabilities
            if item.provenance.adapter_id == "project-marker"
            for provided in item.manifest.provides
            if provided in {"analysis.code-relationships", "cross-session-memory"}
        }
    )
    return tuple(
        AbstractCapabilityRequirement(
            capability=capability,
            strength=RequirementStrength.RECOMMENDED,
            originating_packs=("project-local-discovery",),
            originating_requirements=(f"discover-{capability}",),
            reasons=("A verified project-local provider is available.",),
            verification=("Verify the selected provider remains locally available.",),
        )
        for capability in capabilities
    )


def _load_rejections(root: Path) -> tuple[str, ...]:
    path = root / ".ai-project" / "rejections.json"
    if not path.is_file():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    values = payload.get("capabilities", ())
    if not isinstance(values, list) or not all(
        isinstance(item, str) and item for item in values
    ):
        raise ValueError(".ai-project/rejections.json capabilities must be strings")
    return tuple(sorted(set(values)))


def _with_scale_facts(repository: RepositorySnapshot) -> RepositorySnapshot:
    root = repository.root
    package_manifests = tuple(root.rglob("package.json"))
    python_manifests = tuple(root.rglob("pyproject.toml"))
    workspace_markers = tuple(root.rglob("pnpm-workspace.yaml"))
    root_package = root / "package.json"
    node_workspaces = False
    if root_package.is_file():
        try:
            payload = json.loads(root_package.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = {}
        node_workspaces = bool(payload.get("workspaces"))
    manifest_count = len(package_manifests) + len(python_manifests)
    is_monorepo = node_workspaces or bool(workspace_markers) or manifest_count >= 3
    size = "large" if is_monorepo and manifest_count >= 3 else "small"
    retained = tuple(
        fact
        for fact in repository.facts
        if fact.key not in {"is_monorepo", "repository_size"}
    )
    facts = (
        *retained,
        RepositoryFact(
            key="is_monorepo",
            value=str(is_monorepo).lower(),
            confidence=FactConfidence.CONFIRMED,
            sources=("workspace and package manifests",),
        ),
        RepositoryFact(
            key="repository_size",
            value=size,
            confidence=FactConfidence.CONFIRMED,
            sources=(f"package manifests: {manifest_count}",),
        ),
    )
    return repository.model_copy(
        update={"facts": tuple(sorted(facts, key=lambda item: item.key))}
    )
