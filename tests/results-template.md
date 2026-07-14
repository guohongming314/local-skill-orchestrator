# Evaluation result template

Evaluation artifacts under `tests/results/` are deterministic, versioned JSON produced by offline runners. A result must record:

- input/sample digest and schema version;
- aggregate metrics with numerator and denominator;
- per-sample expected and actual outcomes;
- traceable evidence for routing, permissions, override handling, configuration, and drift detection;
- the versioned threshold configuration used by release gates.

## Task routing

Generate `tests/results/task-routing.json` with:

```bash
uv run python -m vibe.evaluation.task_routing --samples tests/scenarios/tasks --output tests/results/task-routing.json --thresholds tests/evaluation/task-routing/thresholds.json
```
