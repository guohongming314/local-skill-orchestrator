from typing import Literal

import pytest
from pydantic import ValidationError

from vibe.models.codex_skill import CodexSkillMetadata, SkillToolDependency


def test_codex_skill_metadata_defaults_enable_implicit_invocation() -> None:
    metadata = CodexSkillMetadata()

    assert metadata.allow_implicit_invocation is True
    assert metadata.tool_dependencies == ()


@pytest.mark.parametrize("transport", [None, "stdio", "streamable_http"])
def test_skill_tool_dependency_accepts_mcp_metadata(
    transport: Literal["stdio", "streamable_http"] | None,
) -> None:
    dependency = SkillToolDependency(
        dependency_type="mcp",
        value="filesystem",
        description="Read project files",
        transport=transport,
        url="https://example.test/mcp",
    )

    assert dependency.dependency_type == "mcp"
    assert dependency.value == "filesystem"
    assert dependency.description == "Read project files"
    assert dependency.transport == transport
    assert dependency.url == "https://example.test/mcp"


def test_skill_tool_dependency_rejects_unknown_dependency_type() -> None:
    with pytest.raises(ValidationError, match="dependency_type"):
        SkillToolDependency.model_validate({"dependency_type": "shell", "value": "rg"})


def test_skill_tool_dependency_requires_nonempty_value() -> None:
    with pytest.raises(ValidationError, match="value"):
        SkillToolDependency(dependency_type="mcp", value="")


def test_skill_tool_dependency_rejects_unsupported_transport() -> None:
    with pytest.raises(ValidationError, match="transport"):
        SkillToolDependency.model_validate(
            {
                "dependency_type": "mcp",
                "value": "filesystem",
                "transport": "websocket",
            }
        )


@pytest.mark.parametrize("model", [CodexSkillMetadata, SkillToolDependency])
def test_codex_skill_models_reject_unknown_fields(model: type[object]) -> None:
    data: dict[str, object]
    if model is CodexSkillMetadata:
        data = {"unknown": True}
    else:
        data = {"dependency_type": "mcp", "value": "filesystem", "unknown": True}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate(data)  # type: ignore[attr-defined]


def test_codex_skill_models_are_frozen() -> None:
    metadata = CodexSkillMetadata()
    dependency = SkillToolDependency(dependency_type="mcp", value="filesystem")

    with pytest.raises(ValidationError, match="frozen"):
        metadata.allow_implicit_invocation = False
    with pytest.raises(ValidationError, match="frozen"):
        dependency.value = "other"
