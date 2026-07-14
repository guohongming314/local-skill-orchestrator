# Task-routing evaluation baseline v1

## Purpose

This baseline records the first deterministic offline measurement of the versioned E10.3 task sample set. It contains no online telemetry and performs no policy learning. Each aggregate is traceable to the per-sample evidence in `tests/results/task-routing.json`.

## Inputs

- Sample schema version: `1`
- Sample count: 90 (30 simple, 30 normal, 30 high-risk)
- Sample-set digest: `82ebe6c4dcfed3f49bf81152af51ef516ef5e5dec4cf88668cb41c6de36b1123`
- Runner/result schema version: `1`

## First measured baseline

The measurements below were recorded before release thresholds were fixed:

| Metric | Measured value |
| --- | ---: |
| Intent accuracy | 1.000000 |
| Risk accuracy | 1.000000 |
| Capability Recall@K | 1.000000 |
| Unrelated-capability selection rate | 0.000000 |
| Context Capsule mean size | 827 bytes |
| User override handling rate | 1.000000 (20/20) |
| Erroneous permission request rate | 0.000000 |
| End-to-end configuration success rate | 1.000000 |
| Doctor drift-detection rate | 1.000000 |

## Reviewed release thresholds

The versioned machine-readable thresholds are in `tests/evaluation/task-routing/thresholds.json`. Release candidates must retain perfect correctness/success rates for this golden set, zero unrelated capability and permission errors, and a mean capsule size no greater than 4096 bytes. The size ceiling intentionally leaves room for useful context while preventing unbounded growth.

Threshold failures name the metric, bound, actual value, and signed difference. Changes require an explicit schema/configuration review and must never be learned or silently updated by the runner.

## Reproduction

```bash
uv run python -m vibe.evaluation.task_routing --samples tests/scenarios/tasks --output tests/results/task-routing.json --thresholds tests/evaluation/task-routing/thresholds.json
```
