"""Deterministic, write-free rendering of project AI configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from vibe.inventory.service import InventoryResult
from vibe.materialize.capability_manager import (
    render_capability_manager_references,
    render_capability_manager_skill,
)
from vibe.materialize.codex_metadata import render_capability_manager_metadata
from vibe.materialize.project_hooks import ProjectHookPolicy, render_project_hooks
from vibe.models.base import VersionedModel
from vibe.models.blueprint import Blueprint
from vibe.models.capability import CapabilityManifest
from vibe.models.codex_skill import CodexSkillMetadata
from vibe.models.resolution import ResolutionPlan, ResolutionStatus
from vibe.practices.models import RequirementStrength
from vibe.resolver.requirements import AbstractCapabilityRequirement


@dataclass(frozen=True, order=True)
class RenderedFile:
    path: str
    content: str


@dataclass(frozen=True)
class RenderedProject:
    files: tuple[RenderedFile, ...]

    def as_dict(self) -> dict[str, str]:
        return {item.path: item.content for item in self.files}

    def snapshot_bytes(self) -> bytes:
        return "".join(f"=== {item.path} ===\n{item.content}" for item in self.files).encode(
            "utf-8"
        )


class CapabilityLockEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    source: str = Field(min_length=1)
    version: str | None = None
    content_digest: str = Field(min_length=8)
    publisher: str | None = None
    source_verified: bool | None = None
    publisher_verified: bool | None = None
    publisher_verification: str | None = None
    digest_verified: bool | None = None
    permission_level: str | None = None
    codex_skill: CodexSkillMetadata | None = None
    hook_approved: bool | None = None
    hook_approval_provenance: str | None = None
    hook_trust_digest: str | None = None
    hook_events: tuple[str, ...] | None = None
    hook_permissions: tuple[str, ...] | None = None
    hook_script_path: str | None = None
    hook_script_digest: str | None = None


class CapabilityLock(VersionedModel):
    inventory_digest: str = Field(min_length=8)
    providers: tuple[CapabilityLockEntry, ...]


class RenderedCapabilities(VersionedModel):
    blueprint_digest: str = Field(min_length=8)
    inventory_digest: str = Field(min_length=8)
    resolutions: tuple[dict[str, Any], ...]


class ProjectPolicy(VersionedModel):
    risk_level: str
    target_platforms: tuple[str, ...]
    permissions: tuple[str, ...]


class ProjectWorkflows(VersionedModel):
    workflows: tuple[dict[str, Any], ...]


class ProjectTaskPolicies(VersionedModel):
    policies: tuple[dict[str, Any], ...]


class CapabilityUsage(VersionedModel):
    routes: tuple[dict[str, Any], ...]


class EvaluatedCapabilityRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: str = Field(min_length=1)
    strength: RequirementStrength
    reasons: tuple[str, ...] = Field(min_length=1)
    verification: tuple[str, ...] = Field(min_length=1)
    selected_provider: None = None


class CapabilityRequirements(VersionedModel):
    requirements: tuple[EvaluatedCapabilityRequirement, ...]


def render_project_configuration(
    blueprint: Blueprint,
    resolution_plan: ResolutionPlan,
    inventory: InventoryResult,
    *,
    requirements: tuple[AbstractCapabilityRequirement, ...],
    hook_policy: ProjectHookPolicy | None = None,
) -> RenderedProject:
    """Render all project configuration in memory without touching the target project."""
    if resolution_plan.inventory_digest != inventory.inventory_digest:
        raise ValueError("resolution plan inventory digest does not match inventory")

    manifests = {item.manifest.capability_id: item.manifest for item in inventory.capabilities}
    selected = _selected_manifests(resolution_plan, manifests)
    hook_render = render_project_hooks(hook_policy) if hook_policy is not None else None
    hook_lock = (
        CapabilityLockEntry(
            provider_id="hook.project",
            kind="hook",
            scope="project",
            source=".codex/hooks.json",
            content_digest=hook_render.content_digest,
            hook_approved=hook_policy.approved,
            hook_approval_provenance=hook_policy.approval_provenance,
            hook_trust_digest=hook_render.trust_digest,
            hook_events=tuple(sorted(set(hook_policy.events))),
            hook_permissions=tuple(sorted(set(hook_policy.permissions))),
            hook_script_path=hook_policy.script_path,
            hook_script_digest=hook_render.script_digest,
        )
        if hook_policy is not None
        and hook_policy.approved
        and hook_render is not None
        and hook_render.content_digest is not None
        else None
    )
    lock = CapabilityLock(
        inventory_digest=inventory.inventory_digest,
        providers=(
            *tuple(
                CapabilityLockEntry(
                    provider_id=manifest.capability_id,
                    kind=manifest.kind.value,
                    scope=manifest.scope.value,
                    source=manifest.source,
                    version=manifest.version,
                    content_digest=manifest.content_digest,
                    codex_skill=manifest.codex_skill,
                )
                for manifest in selected
            ),
            *((hook_lock,) if hook_lock is not None else ()),
        ),
    )
    capabilities = RenderedCapabilities(
        blueprint_digest=resolution_plan.blueprint_digest,
        inventory_digest=resolution_plan.inventory_digest,
        resolutions=tuple(
            resolution.model_dump(mode="json")
            for resolution in sorted(
                resolution_plan.resolutions,
                key=lambda item: (item.requirement, item.status.value, item.capability_id or ""),
            )
        ),
    )
    policy = ProjectPolicy(
        risk_level=blueprint.risk_level.value,
        target_platforms=tuple(sorted(blueprint.target_platforms)),
        permissions=tuple(
            sorted(permission.value for manifest in selected for permission in manifest.permissions)
        ),
    )
    workflows = ProjectWorkflows(
        workflows=(
            {"name": "develop", "steps": ["plan", "test", "implement", "verify"]},
            {"name": "change", "steps": ["preview", "approve", "apply", "verify"]},
        )
    )
    task_policies = ProjectTaskPolicies(
        policies=(
            {"name": "testing", "value": blueprint.preferences.get("testing", "verify")},
            {"name": "parallelism", "value": blueprint.preferences.get("parallelism", 1)},
            {"name": "risk", "value": blueprint.risk_level.value},
        )
    )
    usage = CapabilityUsage(routes=_usage_routes(selected))
    evaluated_requirements = CapabilityRequirements(
        requirements=tuple(
            EvaluatedCapabilityRequirement(
                capability=requirement.capability,
                strength=requirement.strength,
                reasons=requirement.reasons,
                verification=requirement.verification,
            )
            for requirement in sorted(requirements, key=lambda item: item.capability)
        )
    )

    capability_references = render_capability_manager_references(resolution_plan, inventory)
    skill_root = ".agents/skills/project-capability-manager"
    files = {
        ".ai-project/blueprint.yaml": _yaml(blueprint.model_dump(mode="json")),
        ".ai-project/capabilities.yaml": _yaml(capabilities.model_dump(mode="json")),
        ".ai-project/capabilities.lock": _yaml(lock.model_dump(mode="json", exclude_none=True)),
        ".ai-project/capability-requirements.yaml": _yaml(
            evaluated_requirements.model_dump(mode="json")
        ),
        ".ai-project/policy.yaml": _yaml(policy.model_dump(mode="json")),
        ".ai-project/decisions.md": _decisions(blueprint, resolution_plan),
        ".ai-project/quality-gates.md": _quality_gates(),
        ".ai-project/workflows.yaml": _yaml(workflows.model_dump(mode="json")),
        ".ai-project/task-policies.yaml": _yaml(task_policies.model_dump(mode="json")),
        ".ai-project/capability-usage.yaml": _yaml(usage.model_dump(mode="json")),
        f"{skill_root}/SKILL.md": render_capability_manager_skill(blueprint),
        f"{skill_root}/agents/openai.yaml": render_capability_manager_metadata(),
        **{f"{skill_root}/{path}": content for path, content in capability_references.items()},
        **(
            {item.path: item.content for item in hook_render.files}
            if hook_render is not None
            else {}
        ),
    }
    return RenderedProject(tuple(RenderedFile(path, files[path]) for path in sorted(files)))


def validate_rendered_yaml(rendered: RenderedProject) -> None:
    """Parse and schema-validate every generated YAML configuration."""
    files = rendered.as_dict()
    validators: dict[str, type[VersionedModel]] = {
        ".ai-project/blueprint.yaml": Blueprint,
        ".ai-project/capabilities.yaml": RenderedCapabilities,
        ".ai-project/capabilities.lock": CapabilityLock,
        ".ai-project/policy.yaml": ProjectPolicy,
        ".ai-project/workflows.yaml": ProjectWorkflows,
        ".ai-project/task-policies.yaml": ProjectTaskPolicies,
        ".ai-project/capability-usage.yaml": CapabilityUsage,
        ".ai-project/capability-requirements.yaml": CapabilityRequirements,
    }
    for path, model in validators.items():
        payload = yaml.safe_load(files[path])
        model.model_validate(payload)


def _selected_manifests(
    plan: ResolutionPlan, manifests: dict[str, CapabilityManifest]
) -> tuple[CapabilityManifest, ...]:
    selected_ids: set[str] = set()
    for resolution in plan.resolutions:
        if resolution.status is ResolutionStatus.SELECTED:
            if resolution.capability_id is None:
                raise ValueError("selected resolution is missing a provider")
            selected_ids.add(resolution.capability_id)
    missing = sorted(identifier for identifier in selected_ids if identifier not in manifests)
    if missing:
        raise ValueError(f"selected providers missing from inventory: {', '.join(missing)}")
    return tuple(manifests[identifier] for identifier in sorted(selected_ids))


def _usage_routes(selected: tuple[CapabilityManifest, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "provider_id": manifest.capability_id,
            "provides": sorted(manifest.provides),
            "permissions": sorted(permission.value for permission in manifest.permissions),
        }
        for manifest in selected
    )


def _yaml(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(
        payload,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
    )


def _decisions(blueprint: Blueprint, resolution_plan: ResolutionPlan) -> str:
    lines = [
        "# Project decisions",
        "",
        f"- Project: {blueprint.project_name}",
        f"- Goal: {blueprint.goal}",
        f"- Lifecycle: {blueprint.lifecycle_stage.value}",
        f"- Risk: {blueprint.risk_level.value}",
        "",
        "## Constraints",
    ]
    lines.extend(
        f"- {item.name}: {item.value} ({'locked' if item.locked else 'advisory'})"
        for item in sorted(blueprint.constraints, key=lambda item: item.name)
    )
    lines.extend(["", "## Preferences"])
    lines.extend(f"- {key}: {blueprint.preferences[key]}" for key in sorted(blueprint.preferences))
    recommendations = [
        item
        for item in resolution_plan.resolutions
        if item.status is ResolutionStatus.GAP and item.recommendation is not None
    ]
    if recommendations:
        lines.extend(["", "## Capability gap recommendations"])
        for resolution in sorted(recommendations, key=lambda item: item.requirement):
            recommendation = resolution.recommendation
            if recommendation is None:
                continue
            lines.extend(["", f"### {resolution.requirement}: {recommendation.why}"])
            for index, candidate in enumerate(recommendation.candidates, start=1):
                permissions = ", ".join(permission.value for permission in candidate.permissions)
                remote_details = ""
                if candidate.permission_level is not None:
                    remote_details = (
                        f"; level: {candidate.permission_level}; "
                        f"approval: {candidate.approval_required}; "
                        f"scores: fit={candidate.fit_score}, trust={candidate.trust_score}, "
                        f"risk={candidate.risk_score}; "
                        f"risk flags: {', '.join(candidate.risk_flags or ()) or 'none'}"
                    )
                lines.append(
                    f"{index}. {candidate.provider} ({candidate.kind.value}, "
                    f"{candidate.strength.value}) — permissions: {permissions}"
                    f"{remote_details}; why: {candidate.why}"
                )
    return "\n".join(lines) + "\n"


def _quality_gates() -> str:
    return """# Quality gates

Before completing a change:

1. Run focused verification.
2. Run the full test suite.
3. Run lint and static type checks.
4. Build the distributable artifact.
5. Require CI to pass before merge.
"""
