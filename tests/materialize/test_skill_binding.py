from __future__ import annotations

from pathlib import Path

import pytest

from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.service import InventoryResult, InventoryService
from vibe.materialize.skill_binding import build_skill_binding_proposals
from vibe.models.capability import CapabilityScope
from vibe.models.resolution import CapabilityResolution, ResolutionPlan, ResolutionStatus


def _skill(root: Path, name: str, body: str = "Instructions\n") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_bytes(
        f"---\r\nname: {name}\r\ndescription: {name} helper\r\n---\r\n{body}".encode()
    )
    return directory


def _inventory(root: Path, scope: CapabilityScope) -> InventoryResult:
    return InventoryService().scan([AgentSkillAdapter(roots=(SkillRoot(root, scope),))])


def _plan(inventory: InventoryResult, *capability_ids: str) -> ResolutionPlan:
    return ResolutionPlan(
        blueprint_digest="blueprint-digest",
        inventory_digest=inventory.inventory_digest,
        resolutions=tuple(
            CapabilityResolution(
                requirement=f"requirement-{index}",
                status=ResolutionStatus.SELECTED,
                capability_id=capability_id,
                reason="selected",
            )
            for index, capability_id in enumerate(capability_ids)
        ),
    )


def test_copies_selected_user_skill_with_exact_text_content(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    skill = _skill(user_root, "formatter")
    inventory = _inventory(user_root, CapabilityScope.USER)

    proposals = build_skill_binding_proposals(
        tmp_path / "project", _plan(inventory, "skill.formatter"), inventory
    )

    assert [proposal.path for proposal in proposals] == [
        ".agents/skills/formatter/SKILL.md"
    ]
    assert proposals[0].desired_content == (skill / "SKILL.md").read_bytes().decode()


def test_copies_verified_references_and_openai_metadata(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    skill = _skill(user_root, "database", "Read [guide](references/guide.md).\r\n")
    (skill / "references").mkdir()
    (skill / "references/guide.md").write_text("guide\n", encoding="utf-8")
    (skill / "agents").mkdir()
    (skill / "agents/openai.yaml").write_text(
        "policy:\n  allow_implicit_invocation: false\n", encoding="utf-8"
    )
    inventory = _inventory(user_root, CapabilityScope.USER)

    proposals = build_skill_binding_proposals(
        tmp_path / "project", _plan(inventory, "skill.database"), inventory
    )

    assert [proposal.path for proposal in proposals] == [
        ".agents/skills/database/SKILL.md",
        ".agents/skills/database/agents/openai.yaml",
        ".agents/skills/database/references/guide.md",
    ]


def test_project_scoped_skill_at_target_is_not_bound(tmp_path: Path) -> None:
    project = tmp_path / "project"
    skill_root = project / ".agents/skills"
    _skill(skill_root, "formatter")
    inventory = _inventory(skill_root, CapabilityScope.PROJECT)

    assert build_skill_binding_proposals(
        project, _plan(inventory, "skill.formatter"), inventory
    ) == ()


def test_unverified_skill_is_refused_without_reading_secret_or_outside_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_root = tmp_path / "user"
    skill = _skill(
        user_root,
        "unsafe",
        "Read [secret](credentials.pem) and [outside](outside.md).\n",
    )
    (skill / "credentials.pem").write_text("SECRET", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("OUTSIDE", encoding="utf-8")
    (skill / "outside.md").symlink_to(outside)
    inventory = _inventory(user_root, CapabilityScope.USER)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path in {outside, skill / "credentials.pem"}:
            raise AssertionError("unsafe file was read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    with pytest.raises(ValueError, match="unverified selected Skill"):
        build_skill_binding_proposals(
            tmp_path / "project", _plan(inventory, "skill.unsafe"), inventory
        )


@pytest.mark.parametrize("name", ["project-capability-manager"])
def test_reserved_skill_name_is_refused(tmp_path: Path, name: str) -> None:
    user_root = tmp_path / "user"
    _skill(user_root, name)
    inventory = _inventory(user_root, CapabilityScope.USER)

    with pytest.raises(ValueError, match="conflicts with generated Skill"):
        build_skill_binding_proposals(
            tmp_path / "project", _plan(inventory, f"skill.{name}"), inventory
        )


def test_duplicate_selected_skill_name_is_refused(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    _skill(user_root, "formatter")
    inventory = _inventory(user_root, CapabilityScope.USER)

    with pytest.raises(ValueError, match="duplicate selected Skill name"):
        build_skill_binding_proposals(
            tmp_path / "project",
            _plan(inventory, "skill.formatter", "skill.formatter"),
            inventory,
        )
