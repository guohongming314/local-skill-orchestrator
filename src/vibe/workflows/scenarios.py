"""Deterministic task-scenario registry and risk classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vibe.models.base import VersionedModel
from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    Risk,
    RiskDimension,
    RiskFactor,
    RiskLevel,
    ScopeLevel,
    TaskOperation,
)
from vibe.models.task import WorkflowMode


class ScenarioId(StrEnum):
    BUG = "bug"
    FEATURE = "feature"
    REFACTOR = "refactor"
    SECURITY = "security"
    MIGRATION = "migration"
    REVIEW = "review"
    PERFORMANCE = "performance"
    DEPENDENCY_UPGRADE = "dependency-upgrade"
    TESTING = "testing"
    UI_ACCESSIBILITY = "ui-accessibility"
    DOCUMENTATION = "documentation"
    RELEASE = "release"
    INCIDENT = "incident"
    EXPLORATION = "exploration"


P0_SCENARIOS = frozenset(
    {
        ScenarioId.BUG,
        ScenarioId.FEATURE,
        ScenarioId.REFACTOR,
        ScenarioId.SECURITY,
        ScenarioId.MIGRATION,
        ScenarioId.REVIEW,
    }
)


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario: ScenarioId
    risk_policy: str
    safe_fallback: str
    minimum_risk: RiskLevel = RiskLevel.LOW
    force_approval: bool = False
    force_rollback: bool = False


class ScenarioRequest(VersionedModel):
    scenario: ScenarioId
    scope: ScopeLevel
    data_sensitivity: DataSensitivity
    reversibility: Reversibility
    operations: frozenset[TaskOperation]


@dataclass(frozen=True)
class ScenarioClassification:
    scenario: ScenarioId
    risk: Risk
    workflow_mode: WorkflowMode
    required_phases: tuple[str, ...]
    includes_write_phase: bool
    explanation: tuple[str, ...]


SCENARIO_REGISTRY: dict[ScenarioId, ScenarioDefinition] = {
    scenario: ScenarioDefinition(
        scenario=scenario,
        risk_policy="Derive risk from scope, data sensitivity, reversibility, and operations.",
        safe_fallback="Use a rigorous workflow and request approval when signals are incomplete.",
        minimum_risk=(
            RiskLevel.HIGH
            if scenario
            in {
                ScenarioId.SECURITY,
                ScenarioId.MIGRATION,
                ScenarioId.RELEASE,
                ScenarioId.INCIDENT,
            }
            else RiskLevel.LOW
        ),
        force_approval=scenario
        in {ScenarioId.SECURITY, ScenarioId.MIGRATION, ScenarioId.RELEASE, ScenarioId.INCIDENT},
        force_rollback=scenario is ScenarioId.MIGRATION,
    )
    for scenario in ScenarioId
}


_FIXTURE_OPERATIONS = {
    ScenarioId.REVIEW: frozenset({TaskOperation.READ_PROJECT}),
    ScenarioId.EXPLORATION: frozenset({TaskOperation.READ_PROJECT}),
    ScenarioId.SECURITY: frozenset({TaskOperation.MODIFY_SECURITY}),
    ScenarioId.MIGRATION: frozenset({TaskOperation.MIGRATE_DATA}),
    ScenarioId.RELEASE: frozenset({TaskOperation.DEPLOY}),
    ScenarioId.INCIDENT: frozenset(
        {TaskOperation.EXECUTE_COMMAND, TaskOperation.NETWORK}
    ),
}
SCENARIO_FIXTURES: dict[ScenarioId, ScenarioRequest] = {
    scenario: ScenarioRequest(
        scenario=scenario,
        scope=ScopeLevel.LOCAL,
        data_sensitivity=DataSensitivity.PUBLIC,
        reversibility=Reversibility.REVERSIBLE,
        operations=_FIXTURE_OPERATIONS.get(
            scenario, frozenset({TaskOperation.WRITE_PROJECT})
        ),
    )
    for scenario in ScenarioId
}

_LEVEL_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}
_WRITE_OPERATIONS = frozenset(
    {
        TaskOperation.WRITE_PROJECT,
        TaskOperation.EXECUTE_COMMAND,
        TaskOperation.DEPLOY,
        TaskOperation.MIGRATE_DATA,
        TaskOperation.MODIFY_SECURITY,
        TaskOperation.HANDLE_PAYMENT,
    }
)


def classify_scenario(request: ScenarioRequest) -> ScenarioClassification:
    """Classify explicit task signals without model-based intent parsing."""
    definition = SCENARIO_REGISTRY[request.scenario]
    factors = (
        _scope_factor(request.scope),
        _sensitivity_factor(request.data_sensitivity),
        _reversibility_factor(request.reversibility),
        _operations_factor(request.operations),
    )
    derived = max((factor.level for factor in factors), key=_LEVEL_ORDER.__getitem__)
    level = max((derived, definition.minimum_risk), key=_LEVEL_ORDER.__getitem__)
    rollback = (
        definition.force_rollback
        or request.reversibility is Reversibility.IRREVERSIBLE
        or TaskOperation.MIGRATE_DATA in request.operations
    )
    approval = (
        definition.force_approval
        or _LEVEL_ORDER[level] >= _LEVEL_ORDER[RiskLevel.HIGH]
        or TaskOperation.HANDLE_PAYMENT in request.operations
    )
    risk = Risk(
        level=level,
        factors=factors,
        requires_approval=approval,
        rollback_required=rollback,
    )
    includes_write = bool(request.operations & _WRITE_OPERATIONS)
    phases = ["classify", "explore"]
    if approval:
        phases.append("approval")
    if includes_write:
        phases.append("write")
    if rollback:
        phases.append("rollback")
    phases.append("verify")
    return ScenarioClassification(
        scenario=request.scenario,
        risk=risk,
        workflow_mode=_workflow_mode(level),
        required_phases=tuple(phases),
        includes_write_phase=includes_write,
        explanation=tuple(factor.rationale for factor in factors),
    )


def _scope_factor(scope: ScopeLevel) -> RiskFactor:
    level = {
        ScopeLevel.LOCAL: RiskLevel.LOW,
        ScopeLevel.MULTI_COMPONENT: RiskLevel.MEDIUM,
        ScopeLevel.CROSS_SYSTEM: RiskLevel.HIGH,
    }[scope]
    return RiskFactor(
        dimension=RiskDimension.SCOPE,
        level=level,
        rationale=f"Scope is {scope.value}.",
    )


def _sensitivity_factor(sensitivity: DataSensitivity) -> RiskFactor:
    level = {
        DataSensitivity.PUBLIC: RiskLevel.LOW,
        DataSensitivity.INTERNAL: RiskLevel.MEDIUM,
        DataSensitivity.SENSITIVE: RiskLevel.HIGH,
        DataSensitivity.REGULATED: RiskLevel.CRITICAL,
    }[sensitivity]
    return RiskFactor(
        dimension=RiskDimension.DATA_SENSITIVITY,
        level=level,
        rationale=f"Data sensitivity is {sensitivity.value}.",
    )


def _reversibility_factor(reversibility: Reversibility) -> RiskFactor:
    level = {
        Reversibility.REVERSIBLE: RiskLevel.LOW,
        Reversibility.DIFFICULT: RiskLevel.HIGH,
        Reversibility.IRREVERSIBLE: RiskLevel.CRITICAL,
    }[reversibility]
    return RiskFactor(
        dimension=RiskDimension.REVERSIBILITY,
        level=level,
        rationale=f"Change is {reversibility.value}.",
    )


def _operations_factor(operations: frozenset[TaskOperation]) -> RiskFactor:
    if operations & {TaskOperation.HANDLE_PAYMENT}:
        level = RiskLevel.CRITICAL
    elif operations & {
        TaskOperation.NETWORK,
        TaskOperation.DEPLOY,
        TaskOperation.MIGRATE_DATA,
        TaskOperation.MODIFY_SECURITY,
        TaskOperation.EXECUTE_COMMAND,
    }:
        level = RiskLevel.HIGH
    elif TaskOperation.WRITE_PROJECT in operations:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW
    names = ", ".join(sorted(operation.value for operation in operations)) or "none"
    return RiskFactor(
        dimension=RiskDimension.OPERATIONS,
        level=level,
        rationale=f"Requested operations: {names}.",
    )


def _workflow_mode(level: RiskLevel) -> WorkflowMode:
    return {
        RiskLevel.LOW: WorkflowMode.FAST,
        RiskLevel.MEDIUM: WorkflowMode.STANDARD,
        RiskLevel.HIGH: WorkflowMode.RIGOROUS,
        RiskLevel.CRITICAL: WorkflowMode.RIGOROUS,
    }[level]
