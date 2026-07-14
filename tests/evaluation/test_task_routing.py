from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibe.evaluation.samples import TaskSampleSet
from vibe.evaluation.task_routing import (
    EvaluationThresholds,
    TaskRoutingEvaluation,
    ThresholdFailure,
    enforce_thresholds,
    evaluate_sample_set,
    main,
)

SAMPLES = Path("tests/scenarios/tasks/samples.json")


def _samples() -> TaskSampleSet:
    return TaskSampleSet.model_validate_json(SAMPLES.read_text(encoding="utf-8"))


def test_evaluation_is_deterministic_complete_and_traceable() -> None:
    first = evaluate_sample_set(_samples())
    second = evaluate_sample_set(_samples())

    assert first.model_dump_json() == second.model_dump_json()
    assert len(first.samples) == 90
    assert {metric.name for metric in first.metrics} == {
        "intent_accuracy",
        "risk_accuracy",
        "capability_recall_at_k",
        "unrelated_capability_selection_rate",
        "context_capsule_mean_bytes",
        "user_override_handling_rate",
        "erroneous_permission_request_rate",
        "end_to_end_configuration_success_rate",
        "doctor_drift_detection_rate",
    }
    assert all(item.evidence for item in first.samples)
    assert all(any(line.startswith("doctor:") for line in item.evidence) for item in first.samples)
    assert first.metric("intent_accuracy").value == 1.0
    assert first.metric("risk_accuracy").value == 1.0
    assert first.metric("user_override_handling_rate").denominator == 20
    assert all(item.expected_intent == item.actual_intent for item in first.samples)
    assert first.metric("end_to_end_configuration_success_rate").value == 1.0


def test_threshold_failures_name_metric_expected_and_actual() -> None:
    report = evaluate_sample_set(_samples())
    impossible = EvaluationThresholds(
        minimums={"risk_accuracy": 1.01},
        maximums={"erroneous_permission_request_rate": 0.0},
    )

    with pytest.raises(ThresholdFailure, match=r"risk_accuracy.*1\.010000.*1\.000000"):
        enforce_thresholds(report, impossible)


def test_cli_writes_schema_valid_deterministic_report(tmp_path: Path) -> None:
    output = tmp_path / "task-routing.json"
    thresholds = Path("tests/evaluation/task-routing/thresholds.json")

    assert (
        main(
            [
                "--samples",
                str(SAMPLES.parent),
                "--output",
                str(output),
                "--thresholds",
                str(thresholds),
            ]
        )
        == 0
    )
    first = output.read_bytes()
    report = TaskRoutingEvaluation.model_validate_json(first)
    assert report.sample_set_digest

    assert (
        main(
            [
                "--samples",
                str(SAMPLES.parent),
                "--output",
                str(output),
                "--thresholds",
                str(thresholds),
            ]
        )
        == 0
    )
    assert output.read_bytes() == first
    assert json.loads(first)["schema_version"] == "1"
