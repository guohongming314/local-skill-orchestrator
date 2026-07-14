from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner, Result

from vibe.cli import app
from vibe.models.resolution import ResolutionPlan

runner = CliRunner()


def answers(tmp_path: Path) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps(
            {
                "goal": "Build safely",
                "lifecycle_stage": "active-development",
                "risk_level": "medium",
                "preferences": {"testing": "test-first"},
            }
        ),
        encoding="utf-8",
    )
    return path


def invoke(
    root: Path, answer_path: Path, *, run_id: str, dry_run: bool = False
) -> Result:
    args = [
        "init",
        "--path",
        str(root),
        "--answers",
        str(answer_path),
        "--run-id",
        run_id,
        "--checkpoints",
        str(root.parent / f"{run_id}.sqlite3"),
        "--confirm",
        "--json",
    ]
    if dry_run:
        args.append("--dry-run")
    return runner.invoke(app, args)


def project_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_init_dry_run_previews_all_changes_without_writes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    original = b"# User guidance\n\nKeep this.\n"
    (root / "AGENTS.md").write_bytes(original)

    result = invoke(root, answers(tmp_path), run_id="preview", dry_run=True)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "dry-run"
    assert "CREATE .ai-project/blueprint.yaml" in payload["preview"]
    assert "UPDATE AGENTS.md" in payload["preview"]
    assert project_files(root) == {"AGENTS.md": original}


def test_init_applies_complete_configuration_preserves_user_content_and_is_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (root / "AGENTS.md").write_bytes(b"\xef\xbb\xbf# User guidance\n\nKeep this.\n")
    answer_path = answers(tmp_path)

    first = invoke(root, answer_path, run_id="apply-one")

    assert first.exit_code == 0, first.output
    payload = json.loads(first.stdout)
    assert payload["status"] == "completed"
    assert (root / ".ai-project/capabilities.lock").is_file()
    assert (root / ".agents/skills/project-development/SKILL.md").is_file()
    agents = (root / "AGENTS.md").read_text(encoding="utf-8-sig")
    assert agents.startswith("# User guidance\n\nKeep this.\n")
    assert (root / "AGENTS.md").read_bytes().startswith(b"\xef\xbb\xbf")
    assert "local-skill-orchestrator:begin" in agents
    before = project_files(root)

    second = invoke(root, answer_path, run_id="apply-two")

    assert second.exit_code == 0, second.output
    assert project_files(root) == before
    assert json.loads(second.stdout)["applied_paths"] == []


def test_init_review_surfaces_practice_pack_origins_and_reasons(tmp_path: Path) -> None:
    root = tmp_path / "web-project"
    root.mkdir()
    answer_path = tmp_path / "web-answers.json"
    answer_path.write_text(
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

    result = invoke(root, answer_path, run_id="web-review", dry_run=True)

    assert result.exit_code == 0, result.output
    requirements = {
        item["capability"]: item for item in json.loads(result.stdout)["requirements"]
    }
    assert requirements["browser.validation"]["originating_packs"] == ["web-application"]
    assert requirements["browser.validation"]["reasons"] == [
        "Validate user-visible browser behavior"
    ]


def test_init_json_exposes_schema_valid_gap_recommendations(tmp_path: Path) -> None:
    root = tmp_path / "web-project"
    root.mkdir()
    answer_path = tmp_path / "web-answers.json"
    answer_path.write_text(
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

    result = invoke(root, answer_path, run_id="web-recommendations", dry_run=True)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    resolution = ResolutionPlan.model_validate(payload["resolution"])
    browser_gap = next(
        item
        for item in resolution.resolutions
        if item.requirement == "browser.validation" and item.status.value == "gap"
    )
    assert browser_gap.recommendation is not None
    assert [item.provider for item in browser_gap.recommendation.candidates] == [
        "playwright",
        "chrome-devtools",
    ]
    assert payload["decisions"][0].get("recommendation") is not None or any(
        item.get("recommendation") is not None for item in payload["decisions"]
    )
