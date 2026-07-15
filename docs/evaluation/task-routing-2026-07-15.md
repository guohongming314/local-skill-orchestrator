# Task-routing evaluation report — 2026-07-15

## Result

**PASS.** The post-E14 task-routing evaluation satisfies every versioned release
threshold in `tests/evaluation/task-routing/thresholds.json`. No threshold was
changed for this round.

## Inputs

- Baseline: `docs/evaluation/task-routing-baseline.md`
- Evaluated sample schema version: `1`
- Runner/result schema version: `1`
- Sample count: 90 (the E10 distribution retained; 4 samples extended for post-E12/E14 coverage)
- Sample-set digest: `038e8673586b4d7c7ffee86c4ce6e0301caa0d1f3442d0f50f3d6fcd8a426b3e`
- New coverage:
  - 2 conversational-answer samples exercise the natural-language Codex
    classification result and deterministic risk floor.
  - 2 remote-candidate samples cover a relevant selected remote capability and
    an irrelevant rejected remote capability.

## Side-by-side baseline comparison

| Metric | E10 baseline | 2026-07-15 | Delta | Enforced threshold | Result |
| --- | ---: | ---: | ---: | --- | --- |
| Intent accuracy | 1.000000 | 1.000000 | 0.000000 | minimum 1.000000 | PASS |
| Risk accuracy | 1.000000 | 1.000000 | 0.000000 | minimum 1.000000 | PASS |
| Capability Recall@K | 1.000000 | 1.000000 | 0.000000 | minimum 1.000000 | PASS |
| Unrelated-capability selection rate | 0.000000 | 0.000000 | 0.000000 | maximum 0.000000 | PASS |
| Context Capsule mean size | 827 bytes | 829.677778 bytes | +2.677778 bytes | maximum 4096 bytes | PASS |
| User override handling rate | 1.000000 (20/20) | 1.000000 (20/20) | 0.000000 | minimum 1.000000 | PASS |
| Erroneous permission request rate | 0.000000 | 0.000000 | 0.000000 | maximum 0.000000 | PASS |
| End-to-end configuration success rate | 1.000000 | 1.000000 | 0.000000 | minimum 1.000000 | PASS |
| Doctor drift-detection rate | 1.000000 | 1.000000 | 0.000000 | minimum 1.000000 | PASS |

The mean capsule grew by about three bytes after the additional samples, remains
well below the fixed 4096-byte ceiling, and does not represent a threshold
regression. All correctness, selection, permission, configuration, and drift
metrics retain the E10 baseline values.

## Reproduction

```bash
uv run python -m vibe.evaluation.task_routing --enforce
uv run pytest tests/evaluation
```

The machine-readable per-sample evidence is written to
`tests/results/task-routing.json`.
