from enum import StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel


class CapabilityKind(StrEnum):
    SKILL = "skill"
    CLI_TOOL = "cli-tool"
    MCP = "mcp"
    PLUGIN = "plugin"
    HOOK = "hook"


class CapabilityScope(StrEnum):
    PROJECT = "project"
    USER = "user"
    SYSTEM = "system"


class Permission(StrEnum):
    READ_PROJECT = "read-project"
    WRITE_PROJECT = "write-project"
    EXECUTE_COMMAND = "execute-command"
    NETWORK = "network"
    READ_USER_CONFIG = "read-user-config"


class CapabilityManifest(VersionedModel):
    capability_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    name: str = Field(min_length=1)
    kind: CapabilityKind
    scope: CapabilityScope
    source: str = Field(min_length=1)
    provides: tuple[str, ...] = Field(min_length=1)
    permissions: frozenset[Permission] = frozenset()
    version: str | None = None
    content_digest: str = Field(min_length=8)
    verified: bool = False

