"""Bind selected verified user Skills into Codex project discovery scope."""

from __future__ import annotations

from pathlib import Path

from vibe.generated_project_skills import GENERATED_PROJECT_SKILL_NAMES
from vibe.inventory.adapters.agent_skill import skill_bundle_files
from vibe.inventory.service import InventoryResult, inventory_digest
from vibe.materialize.changeset import ChangeProposal
from vibe.materialize.ownership import FileOwnership
from vibe.models.capability import CapabilityKind, CapabilityScope
from vibe.models.resolution import ResolutionPlan, ResolutionStatus


def normalize_bound_skill_inventory(
    root: Path, resolution: ResolutionPlan, inventory: InventoryResult
) -> tuple[ResolutionPlan, InventoryResult]:
    """Represent selected user Skills by their stable project binding identity."""
    selected_ids = {
        item.capability_id
        for item in resolution.resolutions
        if item.status is ResolutionStatus.SELECTED and item.capability_id is not None
    }
    normalized = []
    changed = False
    for item in inventory.capabilities:
        manifest = item.manifest
        if (
            manifest.capability_id in selected_ids
            and manifest.kind is CapabilityKind.SKILL
            and manifest.scope is CapabilityScope.USER
            and item.provenance.adapter_id == "agent-skill"
        ):
            changed = True
            source = (root / ".agents/skills" / manifest.name / "SKILL.md").resolve()
            item = item.__class__(
                manifest=manifest.model_copy(
                    update={"scope": CapabilityScope.PROJECT, "source": str(source)}
                ),
                provenance=item.provenance.__class__(
                    adapter_id=item.provenance.adapter_id, locator=str(source)
                ),
                verification=item.verification,
            )
        normalized.append(item)
    if not changed:
        return resolution, inventory
    capabilities = tuple(normalized)
    digest = inventory_digest(capabilities)
    return (
        resolution.model_copy(update={"inventory_digest": digest}),
        InventoryResult(
            capabilities=capabilities,
            diagnostics=inventory.diagnostics,
            inventory_digest=digest,
        ),
    )


def build_skill_binding_proposals(
    root: Path, resolution: ResolutionPlan, inventory: InventoryResult
) -> tuple[ChangeProposal, ...]:
    """Build deterministic owned proposals for selected user-scope Skills."""
    by_id = {item.manifest.capability_id: item for item in inventory.capabilities}
    selected = []
    names: set[str] = set()
    for item in resolution.resolutions:
        if item.status is not ResolutionStatus.SELECTED or item.capability_id is None:
            continue
        candidate = by_id.get(item.capability_id)
        if candidate is None or candidate.manifest.kind is not CapabilityKind.SKILL:
            continue
        if candidate.provenance.adapter_id != "agent-skill":
            continue
        manifest = candidate.manifest
        if manifest.name in GENERATED_PROJECT_SKILL_NAMES:
            raise ValueError(
                f"selected Skill {manifest.name!r} conflicts with generated Skill"
            )
        if manifest.name in names:
            raise ValueError(f"duplicate selected Skill name: {manifest.name}")
        names.add(manifest.name)
        selected.append(candidate)

    proposals: list[ChangeProposal] = []
    for candidate in sorted(selected, key=lambda item: item.manifest.name):
        manifest = candidate.manifest
        if not manifest.verified or not candidate.verification.verified:
            raise ValueError(f"unverified selected Skill: {manifest.capability_id}")
        target_root = root / ".agents" / "skills" / manifest.name
        source = Path(manifest.source).resolve()
        if manifest.scope is CapabilityScope.PROJECT and source.parent == target_root.resolve():
            continue
        if manifest.scope is not CapabilityScope.USER:
            continue
        bundle = skill_bundle_files(source)
        if bundle.content_digest != manifest.content_digest:
            raise ValueError(f"selected Skill changed after verification: {manifest.capability_id}")
        for file in bundle.files:
            proposals.append(
                ChangeProposal(
                    path=(Path(".agents/skills") / manifest.name / file.relative_path).as_posix(),
                    desired_content=file.content,
                    ownership=FileOwnership.OWNED,
                    source=f"selected-skill-binding:{manifest.capability_id}",
                    reason="bind selected verified user Skill into project scope",
                )
            )
    return tuple(sorted(proposals, key=lambda item: item.path))
