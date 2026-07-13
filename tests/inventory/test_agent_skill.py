from __future__ import annotations

from pathlib import Path

import pytest

from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.inventory.adapters.base import AdapterScanError
from vibe.inventory.service import InventoryService
from vibe.models.capability import CapabilityKind, CapabilityScope, Permission


def write_skill(root: Path, directory: str, frontmatter: str, body: str = "Instructions") -> Path:
    skill = root / directory
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")
    return skill


def test_discovers_project_and_user_skills_with_distinct_scope(tmp_path: Path) -> None:
    project = tmp_path / "project-skills"
    user = tmp_path / "user-skills"
    write_skill(project, "project-tool", "name: project-tool\ndescription: Project helper")
    write_skill(user, "user-tool", "name: user-tool\ndescription: User helper")
    adapter = AgentSkillAdapter(
        roots=(
            SkillRoot(project, CapabilityScope.PROJECT),
            SkillRoot(user, CapabilityScope.USER),
        )
    )

    inventory = InventoryService().scan([adapter])

    assert [(item.manifest.name, item.manifest.scope) for item in inventory.capabilities] == [
        ("project-tool", CapabilityScope.PROJECT),
        ("user-tool", CapabilityScope.USER),
    ]
    assert all(item.manifest.kind is CapabilityKind.SKILL for item in inventory.capabilities)
    assert inventory.diagnostics == ()


def test_parses_metadata_local_dependencies_and_content_digest(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(
        roots,
        "formatter",
        "\n".join(
            (
                "name: formatter",
                "description: Format source files",
                "version: 2.1.0",
                "allowed-tools: Read Bash(ruff:*)",
                "required-tools: python",
            )
        ),
        "Read [the guide](references/guide.md) before running.",
    )
    (skill / "references").mkdir()
    guide = skill / "references" / "guide.md"
    guide.write_text("safe content", encoding="utf-8")
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    first = adapter.scan(adapter.discover()[0])
    guide.write_text("changed safe content", encoding="utf-8")
    second = adapter.scan(adapter.discover()[0])

    assert first.manifest.version == "2.1.0"
    assert first.manifest.permissions == frozenset(
        {Permission.READ_PROJECT, Permission.EXECUTE_COMMAND}
    )
    assert first.manifest.content_digest != second.manifest.content_digest
    assert first.verification.verified
    assert "dependency:references/guide.md" in first.verification.details


def test_malformed_frontmatter_is_reported_without_hiding_valid_skill(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    write_skill(roots, "valid", "name: valid\ndescription: Fine")
    broken = roots / "broken"
    broken.mkdir(parents=True)
    (broken / "SKILL.md").write_text("name: broken\n", encoding="utf-8")
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    inventory = InventoryService().scan([adapter])

    assert [item.manifest.capability_id for item in inventory.capabilities] == ["skill.valid"]
    assert len(inventory.diagnostics) == 1
    assert inventory.diagnostics[0].code == "adapter_scan_failed"
    assert "frontmatter" in inventory.diagnostics[0].message


def test_directory_name_mismatch_and_missing_tool_are_unverified(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    write_skill(
        roots,
        "wrong-directory",
        "name: declared-name\ndescription: Helper\nrequired-tools: definitely-not-installed-vibe",
    )
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert not result.manifest.verified
    assert not result.verification.verified
    assert "directory_name_mismatch:wrong-directory!=declared-name" in result.verification.details
    assert "missing_tool:definitely-not-installed-vibe" in result.verification.details


def test_missing_local_dependency_is_reported_as_unverified(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    write_skill(
        roots,
        "docs-helper",
        "name: docs-helper\ndescription: Helper",
        "Read [missing notes](references/missing.md).",
    )
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert not result.verification.verified
    assert "missing_dependency:references/missing.md" in result.verification.details


def test_secret_like_references_are_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(
        roots,
        "safe-reader",
        "name: safe-reader\ndescription: Helper",
        "See [credentials](credentials.json) and [public docs](references/public.md).",
    )
    (skill / "credentials.json").write_text("TOP-SECRET", encoding="utf-8")
    (skill / "references").mkdir()
    (skill / "references" / "public.md").write_text("public", encoding="utf-8")
    original = Path.read_bytes
    opened: list[str] = []

    def recording_read(path: Path) -> bytes:
        opened.append(path.name)
        if path.name == "credentials.json":
            raise AssertionError("secret-like file was opened")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert "credentials.json" not in opened
    assert "public.md" in opened
    assert "secret_dependency_skipped:credentials.json" in result.verification.details
    assert not result.verification.verified


def test_scan_rejects_locator_outside_configured_roots(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    roots.mkdir()
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    with pytest.raises(AdapterScanError, match="configured roots"):
        from vibe.inventory.adapters.base import AdapterDiscovery

        adapter.scan(AdapterDiscovery(locator=str(tmp_path / "elsewhere" / "SKILL.md")))

