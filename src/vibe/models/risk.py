from enum import StrEnum

from pydantic import Field

from vibe.models.base import VersionedModel


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ScopeLevel(StrEnum):
    LOCAL = "local"
    MULTI_COMPONENT = "multi-component"
    CROSS_SYSTEM = "cross-system"


class DataSensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    REGULATED = "regulated"


class Reversibility(StrEnum):
    REVERSIBLE = "reversible"
    DIFFICULT = "difficult"
    IRREVERSIBLE = "irreversible"


class TaskOperation(StrEnum):
    READ_PROJECT = "read-project"
    WRITE_PROJECT = "write-project"
    EXECUTE_COMMAND = "execute-command"
    NETWORK = "network"
    DEPLOY = "deploy"
    MIGRATE_DATA = "migrate-data"
    MODIFY_SECURITY = "modify-security"
    HANDLE_PAYMENT = "handle-payment"


class RiskDimension(StrEnum):
    SCOPE = "scope"
    DATA_SENSITIVITY = "data-sensitivity"
    REVERSIBILITY = "reversibility"
    OPERATIONS = "operations"


class RiskFactor(VersionedModel):
    dimension: RiskDimension
    level: RiskLevel
    rationale: str = Field(min_length=1)
    mitigations: tuple[str, ...] = ()


class Risk(VersionedModel):
    level: RiskLevel
    factors: tuple[RiskFactor, ...] = Field(min_length=1)
    requires_approval: bool = False
    rollback_required: bool = False