from __future__ import annotations

import json
from pathlib import Path

import pytest
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
    root: Path,
    answer_path: Path,
    *,
    run_id: str,
    dry_run: bool = False,
    extra_args: tuple[str, ...] = (),
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
    args.extend(extra_args)
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
    assert (root / ".agents/skills/project-capability-manager/SKILL.md").is_file()
    assert not (root / ".agents/skills/project-development").exists()
    agents = (root / "AGENTS.md").read_text(encoding="utf-8-sig")
    assert agents.startswith("# User guidance\n\nKeep this.\n")
    assert (root / "AGENTS.md").read_bytes().startswith(b"\xef\xbb\xbf")
    assert "local-skill-orchestrator:begin" in agents
    assert "Codex-native Skill discovery" in agents
    assert "vibe run" not in agents
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


def test_blank_init_without_git_consent_keeps_repository_gitless_and_records_decision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "blank-project"
    root.mkdir()

    result = invoke(root, answers(tmp_path), run_id="blank-decline")

    assert result.exit_code == 0, result.output
    assert not (root / ".git").exists()
    decisions = (root / ".ai-project/decisions.md").read_text(encoding="utf-8")
    assert "- Git initialization: declined" in decisions


def test_blank_init_with_git_consent_initializes_git_before_file_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "blank-project"
    root.mkdir()
    command_observations: list[tuple[tuple[str, ...], Path]] = []

    def run_command(argv: tuple[str, ...], *, cwd: Path, check: bool) -> None:
        assert check is True
        assert not (root / ".ai-project/blueprint.yaml").exists()
        command_observations.append((argv, cwd))
        (root / ".git").mkdir()

    monkeypatch.setattr("vibe.materialize.writer._run_command", run_command)

    result = runner.invoke(
        app,
        [
            "init",
            "--path",
            str(root),
            "--answers",
            str(answers(tmp_path)),
            "--run-id",
            "blank-consent",
            "--checkpoints",
            str(tmp_path / "blank-consent.sqlite3"),
            "--confirm",
            "--git-init",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert command_observations == [(("git", "init"), root.resolve())]
    assert (root / ".git").is_dir()
    assert (root / ".ai-project/blueprint.yaml").is_file()
    decisions = (root / ".ai-project/decisions.md").read_text(encoding="utf-8")
    assert "- Git initialization: approved" in decisions


def test_blank_init_dry_run_shows_git_init_as_pending_command(tmp_path: Path) -> None:
    root = tmp_path / "blank-project"
    root.mkdir()

    result = runner.invoke(
        app,
        [
            "init",
            "--path",
            str(root),
            "--answers",
            str(answers(tmp_path)),
            "--run-id",
            "blank-preview",
            "--checkpoints",
            str(tmp_path / "blank-preview.sqlite3"),
            "--confirm",
            "--git-init",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "PENDING COMMAND git init" in payload["preview"]
    assert not (root / ".git").exists()


def remote_snapshot(root: Path) -> None:
    digest = "sha256:" + "a" * 64
    config = root / ".ai-project" / "remote-candidates.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_ref": "registry:playwright@1.0.0",
                        "name": "playwright",
                        "kind": "cli-tool",
                        "provides": ["browser.validation"],
                        "version": "1.0.0",
                        "digest": digest,
                        "publisher": "Microsoft",
                        "permissions_as_declared": [
                            "read-project",
                            "execute-command",
                        ],
                        "source_tier": 7,
                        "provenance": {
                            "source": "fixture-registry",
                            "publisher": "Microsoft",
                            "digest": digest,
                            "source_verified": True,
                            "publisher_verified": True,
                            "publisher_verification": "allowlist",
                            "digest_verified": True,
                            "permission_level": "L2",
                            "reason": "fixture provenance",
                        },
                    }
                ],
                "evidence": {
                    "registry:playwright@1.0.0": {
                        "platforms": ["codex"],
                        "maintenance": 80,
                        "scan_flags": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_remote_rejection_is_recorded_and_never_reappears_on_reinit(tmp_path: Path) -> None:
    root = tmp_path / "web-project"
    root.mkdir()
    remote_snapshot(root)
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

    first = invoke(
        root,
        answer_path,
        run_id="remote-review",
        dry_run=True,
        extra_args=("--remote-discovery",),
    )
    assert first.exit_code == 0, first.output
    first_resolution = ResolutionPlan.model_validate(json.loads(first.stdout)["resolution"])
    first_gap = next(
        item for item in first_resolution.resolutions if item.requirement == "browser.validation"
    )
    assert first_gap.recommendation is not None
    assert first_gap.recommendation.candidates[0].candidate_ref == (
        "registry:playwright@1.0.0"
    )

    rejected = invoke(
        root,
        answer_path,
        run_id="remote-reject",
        extra_args=(
            "--remote-discovery",
            "--remote-decision",
            "registry:playwright@1.0.0=reject",
        ),
    )
    assert rejected.exit_code == 0, rejected.output
    rejection_payload = json.loads(
        (root / ".ai-project/rejections.json").read_text(encoding="utf-8")
    )
    assert rejection_payload["remote_candidates"] == ["registry:playwright@1.0.0"]
    decisions = (root / ".ai-project/decisions.md").read_text(encoding="utf-8")
    assert "registry:playwright@1.0.0: rejected" in decisions

    again = invoke(
        root,
        answer_path,
        run_id="remote-again",
        dry_run=True,
        extra_args=("--remote-discovery",),
    )
    assert again.exit_code == 0, again.output
    again_resolution = ResolutionPlan.model_validate(json.loads(again.stdout)["resolution"])
    again_gap = next(
        item for item in again_resolution.resolutions if item.requirement == "browser.validation"
    )
    assert again_gap.recommendation is not None
    assert all(
        item.candidate_ref != "registry:playwright@1.0.0"
        for item in again_gap.recommendation.candidates
    )
    assert all(
        item.provider != "playwright" for item in again_gap.recommendation.candidates
    )
