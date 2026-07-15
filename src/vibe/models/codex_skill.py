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
