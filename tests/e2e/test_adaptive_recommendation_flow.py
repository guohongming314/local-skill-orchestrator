from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tests.scenarios.builders import build_scenario
from vibe.cli import app

runner = CliRunner()


def test_recommendation_pause_then_explicit_deferral_reaches_review(tmp_path: Path) -> None:
    root = build_scenario("blank-web-no-browser", tmp_path / "project").root
    checkpoint = tmp_path / "adaptive.sqlite3"
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "goal": "Build a web application",
                "lifecycle_stage": "active-development",
                "risk_level": "medium",
                "project_type": "web-application",
            }
        ),
        encoding="utf-8",
    )
    common = [
        "init",
        "--path",
        str(root),
        "--run-id",
        "adaptive",
        "--checkpoints",
        str(checkpoint),
        "--no-remote-discovery",
        "--json",
    ]

    first = runner.invoke(app, [*common, "--answers", str(answers), "--confirm"])
    assert first.exit_code == 0, first.output
    recommendation = json.loads(first.stdout)
    assert recommendation["status"] == "paused"
    assert recommendation["stage"] == "recommend"
    assert recommendation["review_readiness"]["ready"] is False
    assert "preview" not in recommendation

    reviewed = runner.invoke(
        app,
        [
            *common,
            "--resume",
            "--confirm",
            "--dry-run",
            "--recommendation-decision",
            "*=defer",
        ],
    )
    assert reviewed.exit_code == 0, reviewed.output
    payload = json.loads(reviewed.stdout)
    assert payload["review_readiness"]["ready"] is True
    assert payload["status"] == "dry-run"
    assert payload["preview"]
