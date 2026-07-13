from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner, Result

from vibe.cli import app

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
