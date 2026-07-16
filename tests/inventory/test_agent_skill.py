from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot, skill_bundle_files
from vibe.inventory.adapters.base import AdapterScanError
from vibe.inventory.service import InventoryService
from vibe.models.capability import CapabilityKind, CapabilityScope, Permission


def write_skill(root: Path, directory: str, frontmatter: str, body: str = "Instructions") -> Path:
    skill = root / directory
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")
    return skill


def write_openai_metadata(skill: Path, content: str) -> Path:
    agents = skill / "agents"
    agents.mkdir()
    metadata = agents / "openai.yaml"
    metadata.write_text(content, encoding="utf-8")
    return metadata


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


def test_explicit_provides_separates_resolution_from_native_description(
    tmp_path: Path,
) -> None:
    roots = tmp_path / "skills"
    write_skill(
        roots,
        "debugging",
        "\n".join(
            (
                "name: debugging",
                "description: Diagnose intermittent failures and verify bug fixes",
                "provides: quality.gates, testing unit.testing quality.gates",
            )
        ),
    )
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.provides == (
        "quality.gates",
        "testing",
        "unit.testing",
    )


def test_description_remains_legacy_provides_fallback(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    write_skill(
        roots,
        "legacy",
        "name: legacy\ndescription: Legacy capability identifier",
    )
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.provides == ("Legacy capability identifier",)


def test_normalizes_codex_invocation_metadata_and_mcp_dependencies(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(roots, "database", "name: database\ndescription: Query data")
    write_openai_metadata(
        skill,
        """policy:
  allow_implicit_invocation: false
dependencies:
  tools:
    - type: mcp
      value: postgres
      description: Query the application database
      transport: streamable_http
      url: https://example.test/mcp
""",
    )
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.codex_skill is not None
    assert result.manifest.codex_skill.allow_implicit_invocation is False
    assert [item.model_dump() for item in result.manifest.codex_skill.tool_dependencies] == [
        {
            "dependency_type": "mcp",
            "value": "postgres",
            "description": "Query the application database",
            "transport": "streamable_http",
            "url": "https://example.test/mcp",
        }
    ]
    assert result.verification.verified
    assert "dependency:agents/openai.yaml" in result.verification.details


def test_invalid_openai_metadata_is_unverified_without_aborting_inventory(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    invalid = write_skill(roots, "invalid", "name: invalid\ndescription: Invalid metadata")
    write_openai_metadata(invalid, "policy: []\n")
    write_skill(roots, "valid", "name: valid\ndescription: Valid skill")
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    inventory = InventoryService().scan([adapter])

    assert [item.manifest.name for item in inventory.capabilities] == ["invalid", "valid"]
    invalid_result = inventory.capabilities[0]
    assert invalid_result.manifest.codex_skill is not None
    assert not invalid_result.verification.verified
    assert any(
        detail.startswith("invalid_openai_metadata:")
        for detail in invalid_result.verification.details
    )
    assert inventory.diagnostics == ()


def test_recursive_openai_yaml_is_unverified_without_aborting_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(roots, "recursive", "name: recursive\ndescription: Recursive YAML")
    write_openai_metadata(skill, "policy: {}\n")

    def recursive_yaml(_content: bytes) -> object:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(yaml, "safe_load", recursive_yaml)
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.codex_skill is not None
    assert result.manifest.codex_skill.allow_implicit_invocation is True
    assert not result.verification.verified
    assert "invalid_openai_metadata:RecursionError" in result.verification.details


def test_unknown_openai_policy_key_is_unverified(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(roots, "typo", "name: typo\ndescription: Misspelled policy")
    write_openai_metadata(skill, "policy: {allow_implicit_invocaton: false}\n")
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.codex_skill is not None
    assert result.manifest.codex_skill.allow_implicit_invocation is True
    assert not result.verification.verified
    assert "invalid_openai_metadata:ValueError" in result.verification.details


def test_openai_metadata_content_changes_manifest_digest(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(roots, "mutable", "name: mutable\ndescription: Mutable metadata")
    metadata = write_openai_metadata(
        skill, "policy:\n  allow_implicit_invocation: true\n"
    )
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    first = adapter.scan(adapter.discover()[0])
    metadata.write_text(
        "policy:\n  allow_implicit_invocation: false\n", encoding="utf-8"
    )
    second = adapter.scan(adapter.discover()[0])

    assert first.manifest.content_digest != second.manifest.content_digest


def test_in_tree_symlink_dependency_is_unverified_and_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(
        roots,
        "linked",
        "name: linked\ndescription: Linked dependency",
        "Read [the guide](references/guide.md).",
    )
    references = skill / "references"
    references.mkdir()
    target = references / "real-guide.md"
    target.write_text("do not read through symlink", encoding="utf-8")
    link = references / "guide.md"
    link.symlink_to(target)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path in {link, target}:
            raise AssertionError("symlink dependency target was read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.USER),))

    result = adapter.scan(adapter.discover()[0])

    assert not result.verification.verified
    assert "unsafe_symlink_dependency:references/guide.md" in result.verification.details
    with pytest.raises(ValueError, match="unsafe_symlink_dependency"):
        skill_bundle_files(skill / "SKILL.md")


def test_in_tree_symlink_openai_metadata_is_unverified_and_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(roots, "linked", "name: linked\ndescription: Linked metadata")
    agents = skill / "agents"
    agents.mkdir()
    target = skill / "metadata.yaml"
    target.write_text("policy: {}\n", encoding="utf-8")
    link = agents / "openai.yaml"
    link.symlink_to(target)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path in {link, target}:
            raise AssertionError("symlink metadata target was read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.USER),))

    result = adapter.scan(adapter.discover()[0])

    assert not result.verification.verified
    assert "unsafe_symlink_metadata:agents/openai.yaml" in result.verification.details
    with pytest.raises(ValueError, match="unsafe_symlink_metadata"):
        skill_bundle_files(skill / "SKILL.md")


def test_symlinked_dependency_directory_is_unverified_and_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(
        roots,
        "linked-directory",
        "name: linked-directory\ndescription: Linked directory",
        "Read [the guide](references/guide.md).",
    )
    real_references = skill / "real-references"
    real_references.mkdir()
    target = real_references / "guide.md"
    target.write_text("never read", encoding="utf-8")
    (skill / "references").symlink_to(real_references, target_is_directory=True)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == target:
            raise AssertionError("dependency below symlinked directory was read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.USER),))

    result = adapter.scan(adapter.discover()[0])

    assert not result.verification.verified
    assert "unsafe_symlink_dependency:references/guide.md" in result.verification.details


def test_symlinked_agents_directory_is_unverified_and_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(
        roots, "linked-agents", "name: linked-agents\ndescription: Linked agents"
    )
    real_agents = skill / "real-agents"
    real_agents.mkdir()
    target = real_agents / "openai.yaml"
    target.write_text("policy: {}\n", encoding="utf-8")
    (skill / "agents").symlink_to(real_agents, target_is_directory=True)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == target:
            raise AssertionError("metadata below symlinked directory was read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.USER),))

    result = adapter.scan(adapter.discover()[0])

    assert not result.verification.verified
    assert "unsafe_symlink_metadata:agents/openai.yaml" in result.verification.details


def test_absent_openai_metadata_uses_codex_defaults(tmp_path: Path) -> None:
    roots = tmp_path / "skills"
    write_skill(roots, "defaults", "name: defaults\ndescription: Default metadata")
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert result.manifest.codex_skill is not None
    assert result.manifest.codex_skill.allow_implicit_invocation is True
    assert result.manifest.codex_skill.tool_dependencies == ()


def test_openai_metadata_never_reads_outside_skill_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(roots, "contained", "name: contained\ndescription: Contained")
    outside = tmp_path / "outside.yaml"
    outside.write_text("TOP-SECRET", encoding="utf-8")
    write_openai_metadata(
        skill,
        f"""policy:
  allow_implicit_invocation: true
dependencies:
  tools:
    - type: mcp
      value: filesystem
      url: {outside}
""",
    )
    original = Path.read_bytes
    opened: list[Path] = []

    def recording_read(path: Path) -> bytes:
        opened.append(path.resolve())
        if path.resolve() == outside.resolve():
            raise AssertionError("metadata caused a read outside the Skill directory")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert outside.resolve() not in opened
    assert result.verification.verified


def test_openai_metadata_symlink_outside_skill_directory_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = tmp_path / "skills"
    skill = write_skill(roots, "contained-link", "name: contained-link\ndescription: Safe")
    outside = tmp_path / "outside-agents"
    outside.mkdir()
    outside_metadata = outside / "openai.yaml"
    outside_metadata.write_text("policy: {}\n", encoding="utf-8")
    (skill / "agents").symlink_to(outside, target_is_directory=True)
    original = Path.read_bytes
    opened: list[Path] = []

    def recording_read(path: Path) -> bytes:
        opened.append(path.resolve())
        if path.resolve() == outside_metadata.resolve():
            raise AssertionError("external metadata symlink was read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    adapter = AgentSkillAdapter(roots=(SkillRoot(roots, CapabilityScope.PROJECT),))

    result = adapter.scan(adapter.discover()[0])

    assert outside_metadata.resolve() not in opened
    assert not result.verification.verified
    assert "unsafe_symlink_metadata:agents/openai.yaml" in result.verification.details


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
