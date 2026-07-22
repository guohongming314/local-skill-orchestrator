from vibe.models.blueprint import Blueprint, LifecycleStage, RiskLevel
from vibe.models.decisions import (
    AuthorizationState,
    DecisionProvenance,
    DecisionSource,
    NetworkPolicy,
    PermissionDecision,
    RuntimeNetwork,
    TriState,
)


def test_blueprint_defaults_permissions_and_authorizations_to_unknown() -> None:
    blueprint = Blueprint(
        project_name="orchestrator",
        goal="Compile local capabilities",
        lifecycle_stage=LifecycleStage.ACTIVE_DEVELOPMENT,
        risk_level=RiskLevel.MEDIUM,
        repository_digest="01234567",
    )

    permission_values = (
        blueprint.decisions.read_project.value,
        blueprint.decisions.write_project.value,
        blueprint.decisions.execute_command.value,
        blueprint.decisions.write_outside_project.value,
        blueprint.decisions.access_secrets.value,
    )

    assert permission_values == (TriState.UNKNOWN,) * 5
    assert blueprint.decisions.network_policy.value is NetworkPolicy.UNKNOWN
    assert blueprint.decisions.discovery_approval is AuthorizationState.NOT_REQUESTED
    assert blueprint.decisions.artifact_fetch_approval is AuthorizationState.NOT_REQUESTED
    assert blueprint.decisions.candidate_runtime_network is RuntimeNetwork.UNKNOWN


def test_permission_decision_preserves_user_response_provenance() -> None:
    decision = PermissionDecision(
        value=TriState.ALLOWED,
        provenance=DecisionProvenance(
            source=DecisionSource.USER_RESPONSE,
            reference="permissions.write_project",
        ),
    )

    restored = PermissionDecision.model_validate_json(decision.model_dump_json())

    assert restored == decision
    assert restored.value is TriState.ALLOWED
    assert restored.provenance.source is DecisionSource.USER_RESPONSE
    assert restored.provenance.reference == "permissions.write_project"
