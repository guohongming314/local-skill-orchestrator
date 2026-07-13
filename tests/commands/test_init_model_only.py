from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner, Result

from vibe.cli import app
from vibe.models.blueprint import Blueprint

runner = CliRunner()


def write_answers(path: Path, *, goal: str, lifecycle: str) -> Path:
    answers = path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "goal": goal,
                "lifecycle_stage": lifecycle,
                "risk_level": "low",
                "preferences": {"testing": "test-first"},
            }
        ),
        encoding="utf-8",
    )
    return answers


def invoke(
    root: Path,
    *,
    run_id: str,
    answers: Path | None = None,
    confirm: bool = False,
    cancel: bool = False,
    resume: bool = False,
) -> Result:
    args = [
        "init",
        "--model-only",
        "--path",
        str(root),
        "--run-id",
        run_id,
        "--checkpoints",
        str(root.parent / f"{run_id}.sqlite3"),
        "--output",
        str(root.parent / f"{run_id}-blueprint.json"),
        "--json",
    ]
    if answers is not None:
        args.extend(("--answers", str(answers)))
    if confirm:
        args.append("--confirm")
    if cancel:
        args.append("--cancel")
    if resume:
        args.append("--resume")
    return runner.invoke(app, args)


def test_blank_project_completes_model_only_flow(tmp_path: Path) -> None:
    root = tmp_path / "blank"
    root.mkdir()
    answers = write_answers(tmp_path, goal="Create a local API", lifecycle="exploration")

    result = invoke(root, run_id="blank-run", answers=answers, confirm=True)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    blueprint = Blueprint.model_validate(payload["blueprint"])
    assert payload["status"] == "completed"
    assert blueprint.project_name == "blank"
    assert blueprint.goal == "Create a local API"
    assert payload["field_sources"]["project_name"] == "inferred"
    assert payload["field_sources"]["goal"] == "confirmed"
    assert (tmp_path / "blank-run-blueprint.json").exists()


def test_existing_project_completes_with_existing_repository_digest(tmp_path: Path) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    answers = write_answers(
        tmp_path, goal="Improve the existing service", lifecycle="active-development"
    )

    result = invoke(root, run_id="existing-run", answers=answers, confirm=True)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    blueprint = Blueprint.model_validate(payload["blueprint"])
    assert blueprint.repository_digest != "0" * 64
    assert blueprint.lifecycle_stage.value == "active-development"


def test_cancellation_writes_no_blueprint(tmp_path: Path) -> None:
    root = tmp_path / "cancelled"
    root.mkdir()
    answers = write_answers(tmp_path, goal="Do not persist", lifecycle="exploration")

    result = invoke(root, run_id="cancel-run", answers=answers, cancel=True)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "cancelled"
    assert not (tmp_path / "cancel-run-blueprint.json").exists()


def test_resume_continues_from_saved_interview_checkpoint(tmp_path: Path) -> None:
    root = tmp_path / "resumed"
    root.mkdir()

    paused = invoke(root, run_id="resume-run")
    assert paused.exit_code == 0, paused.output
    paused_payload = json.loads(paused.stdout)
    assert paused_payload["status"] == "paused"
    assert paused_payload["stage"] == "interview"
    assert paused_payload["questions"]
    assert not (tmp_path / "resume-run-blueprint.json").exists()

    answers = write_answers(tmp_path, goal="Resume safely", lifecycle="exploration")
    resumed = invoke(
        root,
        run_id="resume-run",
        answers=answers,
        confirm=True,
        resume=True,
    )
    assert resumed.exit_code == 0, resumed.output
    payload = json.loads(resumed.stdout)
    assert payload["status"] == "completed"
    assert Blueprint.model_validate(payload["blueprint"]).goal == "Resume safely"


def test_unconfirmed_review_writes_no_blueprint(tmp_path: Path) -> None:
    root = tmp_path / "review"
    root.mkdir()
    answers = write_answers(tmp_path, goal="Review first", lifecycle="exploration")

    result = invoke(root, run_id="review-run", answers=answers)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "paused"
    assert payload["stage"] == "review"
    assert "blueprint" in payload
    assert not (tmp_path / "review-run-blueprint.json").exists()


def test_review_answers_can_be_revised_before_confirmation(tmp_path: Path) -> None:
    root = tmp_path / "revise"
    root.mkdir()
    first_answers = write_answers(
        tmp_path, goal="Initial goal", lifecycle="exploration"
    )
    paused = invoke(root, run_id="revise-run", answers=first_answers)
    assert paused.exit_code == 0, paused.output
    assert json.loads(paused.stdout)["stage"] == "review"

    revised_answers = tmp_path / "revised.json"
    revised_answers.write_text(
        json.dumps(
            {
                "goal": "Confirmed revised goal",
                "lifecycle_stage": "active-development",
                "risk_level": "medium",
            }
        ),
        encoding="utf-8",
    )
    resumed = invoke(
        root,
        run_id="revise-run",
        answers=revised_answers,
        confirm=True,
        resume=True,
    )

    assert resumed.exit_code == 0, resumed.output
    payload = json.loads(resumed.stdout)
    blueprint = Blueprint.model_validate(payload["blueprint"])
    assert blueprint.goal == "Confirmed revised goal"
    assert blueprint.lifecycle_stage.value == "active-development"


def test_windows_utf8_bom_answers_are_accepted(tmp_path: Path) -> None:
    root = tmp_path / "bom"
    root.mkdir()
    answers = tmp_path / "bom-answers.json"
    answers.write_text(
        json.dumps(
            {
                "goal": "Accept Windows JSON",
                "lifecycle_stage": "exploration",
                "risk_level": "low",
            }
        ),
        encoding="utf-8-sig",
    )

    result = invoke(root, run_id="bom-run", answers=answers, confirm=True)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "completed"
