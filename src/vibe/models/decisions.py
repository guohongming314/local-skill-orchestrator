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
    REPOSITORY_EVIDENCE = "repository-evidence"
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
