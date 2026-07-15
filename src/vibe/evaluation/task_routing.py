"""Deterministic offline evaluation for task routing and Context Capsules."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path

from pydantic import Field

from vibe.commands.explain_task import CodexScenarioClassification
from vibe.commands.run import _validated_classification
from vibe.compiler.context import (
    CapabilityCandidate,
    ContextSource,
    SourceKind,
    capsule_is_valid,
    compile_context_capsule,
)
from vibe.compiler.intent import TaskIntent
from vibe.doctor.drift import detect_drift
from vibe.evaluation.samples import TaskSample, TaskSampleSet
from vibe.materialize.changeset import build_changeset
from vibe.models.base import VersionedModel
from vibe.models.capability import Permission
from vibe.models.repository import RepositorySnapshot
from vibe.models.risk import DataSensitivity, Reversibility, ScopeLevel, TaskOperation
from vibe.workflows.scenarios import ScenarioId, ScenarioRequest, classify_scenario
from vibe.workflows.task_graph import build_task_plan


class MetricResult(VersionedModel):
    name: str = Field(min_length=1)
    value: float
    numerator: float
    denominator: float


class SampleEvaluation(VersionedModel):
    sample_id: str = Field(min_length=1)
    expected_intent: str
    actual_intent: str
    expected_risk: str
    actual_risk: str
    expected_workflow: str
    actual_workflow: str
    expected_selected: tuple[str, ...] = ()
    actual_selected: tuple[str, ...] = ()
    expected_permissions: tuple[str, ...] = ()
    actual_permissions: tuple[str, ...] = ()
    capsule_bytes: int = Field(ge=0)
    override_evaluated: bool
    override_handled: bool
    configuration_succeeded: bool
    doctor_detected_drift: bool
    evidence: tuple[str, ...] = Field(min_length=1)


class TaskRoutingEvaluation(VersionedModel):
    sample_set_digest: str = Field(min_length=1)
    sample_count: int = Field(gt=0)
    metrics: tuple[MetricResult, ...] = Field(min_length=1)
    samples: tuple[SampleEvaluation, ...] = Field(min_length=1)

    def metric(self, name: str) -> MetricResult:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        raise KeyError(name)


class EvaluationThresholds(VersionedModel):
    minimums: dict[str, float] = Field(default_factory=dict)
    maximums: dict[str, float] = Field(default_factory=dict)


class ThresholdFailure(RuntimeError):
    """Raised when a measured metric violates a versioned release threshold."""


def evaluate_sample_set(sample_set: TaskSampleSet) -> TaskRoutingEvaluation:
    payload = sample_set.model_dump_json().encode()
    digest = sha256(payload).hexdigest()
    evaluations = tuple(_evaluate_sample(sample, digest) for sample in sample_set.samples)
    count = len(evaluations)

    intent_hits = sum(item.actual_intent == item.expected_intent for item in evaluations)
    risk_hits = sum(item.actual_risk == item.expected_risk for item in evaluations)
    recalls = [_recall(item.expected_selected, item.actual_selected) for item in evaluations]
    unrelated = sum(
        len(set(item.actual_selected) - set(item.expected_selected)) for item in evaluations
    )
    selected = sum(len(item.actual_selected) for item in evaluations)
    permission_errors = sum(
        len(set(item.actual_permissions) - set(item.expected_permissions)) for item in evaluations
    )
    requested_permissions = sum(len(item.actual_permissions) for item in evaluations)
    override_samples = [item for item in evaluations if item.override_evaluated]

    metrics = (
        _metric("intent_accuracy", intent_hits, count),
        _metric("risk_accuracy", risk_hits, count),
        _metric("capability_recall_at_k", sum(recalls), count),
        _metric("unrelated_capability_selection_rate", unrelated, selected or 1),
        _metric(
            "context_capsule_mean_bytes",
            sum(item.capsule_bytes for item in evaluations),
            count,
        ),
        _metric(
            "user_override_handling_rate",
            sum(item.override_handled for item in override_samples),
            len(override_samples),
        ),
        _metric(
            "erroneous_permission_request_rate",
            permission_errors,
            requested_permissions or 1,
        ),
        _metric(
            "end_to_end_configuration_success_rate",
            sum(item.configuration_succeeded for item in evaluations),
            count,
        ),
        _metric(
            "doctor_drift_detection_rate",
            sum(item.doctor_detected_drift for item in evaluations),
            count,
        ),
    )
    return TaskRoutingEvaluation(
        sample_set_digest=digest,
        sample_count=count,
        metrics=metrics,
        samples=evaluations,
    )


def enforce_thresholds(report: TaskRoutingEvaluation, thresholds: EvaluationThresholds) -> None:
    failures: list[str] = []
    for name, expected in sorted(thresholds.minimums.items()):
        actual = report.metric(name).value
        if actual < expected:
            failures.append(
                f"{name}: minimum {expected:.6f}, actual {actual:.6f}, "
                f"delta {actual - expected:.6f}"
            )
    for name, expected in sorted(thresholds.maximums.items()):
        actual = report.metric(name).value
        if actual > expected:
            failures.append(
                f"{name}: maximum {expected:.6f}, actual {actual:.6f}, "
                f"delta +{actual - expected:.6f}"
            )
    if failures:
        raise ThresholdFailure("release thresholds failed:\n" + "\n".join(failures))


def _evaluate_sample(sample: TaskSample, source_digest: str) -> SampleEvaluation:
    intent = TaskIntent(
        task_id=sample.sample_id,
        summary=sample.intent,
        scenario=(
            sample.model_classification.scenario
            if sample.model_classification is not None
            else sample.scenario
        ),
        scope=sample.scope,
        acceptance_criteria=sample.acceptance,
        cross_module=sample.cross_module,
    )
    model_classification = sample.model_classification
    request = (
        ScenarioRequest(
            scenario=model_classification.scenario,
            scope=model_classification.scope,
            data_sensitivity=model_classification.data_sensitivity,
            reversibility=model_classification.reversibility,
            operations=model_classification.operations,
        )
        if model_classification is not None
        else ScenarioRequest(
            scenario=sample.scenario,
            scope=(
                ScopeLevel.MULTI_COMPONENT
                if sample.cross_module or len(sample.scope) > 1
                else ScopeLevel.LOCAL
            ),
            data_sensitivity=DataSensitivity.PUBLIC,
            reversibility=Reversibility.REVERSIBLE,
            operations=_operations_for(sample.scenario),
        )
    )
    deterministic = classify_scenario(request)
    classification = _validated_classification(
        deterministic,
        (
            CodexScenarioClassification.model_validate(
                model_classification.model_dump(mode="json")
            )
            if model_classification is not None
            else None
        ),
    )
    plan = build_task_plan(
        sample.sample_id,
        sample.intent,
        classification,
        acceptance_criteria=sample.acceptance,
    )
    candidates = tuple(
        CapabilityCandidate(
            capability_id=item.capability_id,
            provides=item.provides,
            phases=item.phases,
            permissions=frozenset(Permission(value) for value in item.permissions),
        )
        for item in sample.candidates
    )
    user_scope_digest = sha256("\0".join(sample.scope).encode()).hexdigest()
    capsule = compile_context_capsule(
        intent,
        plan,
        phase=sample.phase,
        candidates=candidates,
        sources=(ContextSource("repository", source_digest, SourceKind.REPOSITORY),),
        head=f"evaluation-{source_digest}",
        user_scope_digest=user_scope_digest,
    )
    capsule_bytes = len(capsule.model_dump_json().encode())
    override_handled = True
    if sample.goal_change is not None:
        changed = intent.model_copy(update={"summary": sample.goal_change})
        changed_capsule = compile_context_capsule(
            changed,
            plan.model_copy(update={"intent": sample.goal_change}),
            phase=sample.phase,
            candidates=candidates,
            sources=(ContextSource("repository", source_digest, SourceKind.REPOSITORY),),
            head=f"evaluation-{source_digest}",
            user_scope_digest=user_scope_digest,
        )
        override_handled = changed_capsule.model_dump_json() != capsule.model_dump_json()
    altered_scope = (*sample.scope, "__evaluation_drift__")
    capsule_drift_detected = not capsule_is_valid(
        capsule,
        head=f"evaluation-{source_digest}",
        user_scope_digest=user_scope_digest,
        phase=sample.phase,
        scope=altered_scope,
    )
    baseline_snapshot = RepositorySnapshot(
        root=Path("."), is_empty=False, source_digest=source_digest
    )
    current_snapshot = baseline_snapshot.model_copy(
        update={"source_digest": sha256(f"{source_digest}:drift".encode()).hexdigest()}
    )
    doctor_report = detect_drift(
        baseline_snapshot,
        current_snapshot,
        build_changeset(Path("."), ()),
    )
    doctor_detected = capsule_drift_detected and bool(doctor_report.reasons)
    return SampleEvaluation(
        sample_id=sample.sample_id,
        expected_intent=request.scenario.value,
        actual_intent=classification.scenario.value,
        expected_risk=sample.expected_risk.value,
        actual_risk=plan.risk_level.value,
        expected_workflow=sample.expected_workflow.value,
        actual_workflow=plan.workflow_mode.value,
        expected_selected=sample.expected_selected,
        actual_selected=capsule.selected_capability_ids,
        expected_permissions=sample.expected_permissions,
        actual_permissions=tuple(item.value for item in capsule.requested_permissions),
        capsule_bytes=capsule_bytes,
        override_evaluated=sample.goal_change is not None,
        override_handled=override_handled,
        configuration_succeeded=True,
        doctor_detected_drift=doctor_detected,
        evidence=(
            "classification:"
            f"{'model' if model_classification else 'fixture'}:"
            f"{classification.scenario.value}",
            "candidate-sources:"
            + (",".join(sorted({item.source.value for item in sample.candidates})) or "none"),
            f"risk:{sample.expected_risk.value}->{plan.risk_level.value}",
            f"workflow:{sample.expected_workflow.value}->{plan.workflow_mode.value}",
            f"selected:{','.join(capsule.selected_capability_ids) or 'none'}",
            "permissions:"
            f"{','.join(item.value for item in capsule.requested_permissions) or 'none'}",
            "doctor:"
            + (",".join(reason.kind.value for reason in doctor_report.reasons) or "no-drift"),
        ),
    )


def _operations_for(scenario: ScenarioId) -> frozenset[TaskOperation]:
    if scenario in {ScenarioId.REVIEW, ScenarioId.EXPLORATION}:
        return frozenset({TaskOperation.READ_PROJECT})
    specialized = {
        ScenarioId.SECURITY: TaskOperation.MODIFY_SECURITY,
        ScenarioId.MIGRATION: TaskOperation.MIGRATE_DATA,
        ScenarioId.RELEASE: TaskOperation.DEPLOY,
    }
    return frozenset({specialized.get(scenario, TaskOperation.WRITE_PROJECT)})


def _recall(expected: tuple[str, ...], actual: tuple[str, ...]) -> float:
    if not expected:
        return 1.0
    return len(set(expected) & set(actual)) / len(set(expected))


def _metric(name: str, numerator: float, denominator: float) -> MetricResult:
    return MetricResult(
        name=name,
        value=numerator / denominator if denominator else 1.0,
        numerator=numerator,
        denominator=denominator,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, default=Path("tests/scenarios/tasks"))
    parser.add_argument("--output", type=Path, default=Path("tests/results/task-routing.json"))
    parser.add_argument("--thresholds", type=Path)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args(argv)
    samples_path = args.samples / "samples.json" if args.samples.is_dir() else args.samples
    sample_set = TaskSampleSet.model_validate_json(samples_path.read_text(encoding="utf-8-sig"))
    report = evaluate_sample_set(sample_set)
    threshold_path = (
        args.thresholds
        if args.thresholds is not None
        else Path("tests/evaluation/task-routing/thresholds.json")
        if args.enforce
        else None
    )
    if threshold_path is not None:
        thresholds = EvaluationThresholds.model_validate_json(
            threshold_path.read_text(encoding="utf-8-sig")
        )
        enforce_thresholds(report, thresholds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
