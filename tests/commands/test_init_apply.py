from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner, Result

import vibe.commands.init as init_module
from tests.materialize.test_templates import inputs, requirements
from vibe.cli import app
from vibe.commands.init import _project_changeset
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


def hook_policy(tmp_path: Path, **updates: object) -> Path:
    payload: dict[str, object] = {
        "events": ["PreToolUse", "Stop"],
        "script_path": ".ai-project/hooks/governance.py",
        "script_content": "print('governance')\n",
        "permissions": ["execute-command"],
        "approved": True,
        "approval_provenance": "test:attended-review",
    }
    payload.update(updates)
    path = tmp_path / "hook-policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
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
    assert "CREATE .ai-project/capability-requirements.yaml" in payload["preview"]
    assert "UPDATE AGENTS.md" in payload["preview"]
    assert project_files(root) == {"AGENTS.md": original}


def test_init_hook_policy_dry_run_previews_managed_artifacts_without_writes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    policy_path = hook_policy(tmp_path)

    result = invoke(
        root,
        answers(tmp_path),
        run_id="hook-preview",
        dry_run=True,
        extra_args=("--hook-policy-file", str(policy_path)),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "CREATE .ai-project/hooks/governance.py" in payload["preview"]
    assert "CREATE .codex/hooks.json" in payload["preview"]
    assert "hook_approval_provenance: test:attended-review" in payload["preview"]
    assert "hook_trust_digest:" in payload["preview"]
    assert project_files(root) == {}


def test_init_applies_approved_hook_policy_atomically_and_idempotently(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    policy_path = hook_policy(tmp_path)
    extra = ("--hook-policy-file", str(policy_path))

    first = invoke(root, answers(tmp_path), run_id="hook-apply-one", extra_args=extra)

    assert first.exit_code == 0, first.output
    hooks = json.loads((root / ".codex/hooks.json").read_text(encoding="utf-8"))
    assert set(hooks["hooks"]) == {"PreToolUse", "Stop"}
    assert (root / ".ai-project/hooks/governance.py").read_text(encoding="utf-8") == (
        "print('governance')\n"
    )
    lock = yaml.safe_load(
        (root / ".ai-project/capabilities.lock").read_text(encoding="utf-8")
    )
    hook = next(item for item in lock["providers"] if item["provider_id"] == "hook.project")
    assert hook["hook_approved"] is True
    assert hook["hook_approval_provenance"] == "test:attended-review"
    assert hook["hook_trust_digest"]
    before_hooks = (root / ".codex/hooks.json").read_bytes()
    before_script = (root / ".ai-project/hooks/governance.py").read_bytes()
    before_trust = hook["hook_trust_digest"]

    second = invoke(root, answers(tmp_path), run_id="hook-apply-two", extra_args=extra)

    assert second.exit_code == 0, second.output
    assert ".codex/hooks.json" not in json.loads(second.stdout)["applied_paths"]
    assert ".ai-project/hooks/governance.py" not in json.loads(second.stdout)["applied_paths"]
    assert (root / ".codex/hooks.json").read_bytes() == before_hooks
    assert (root / ".ai-project/hooks/governance.py").read_bytes() == before_script
    updated_lock = yaml.safe_load(
        (root / ".ai-project/capabilities.lock").read_text(encoding="utf-8")
    )
    updated_hook = next(
        item for item in updated_lock["providers"] if item["provider_id"] == "hook.project"
    )
    assert updated_hook["hook_trust_digest"] == before_trust


@pytest.mark.parametrize(
    "updates, error",
    [
        ({"approved": False, "approval_provenance": None}, "must be approved"),
        ({"unexpected": True}, "Extra inputs are not permitted"),
        ({"events": ["NotAnEvent"]}, "Input should be"),
    ],
)
def test_init_rejects_invalid_or_unapproved_hook_policy_without_changes(
    tmp_path: Path, updates: dict[str, object], error: str
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    policy_path = hook_policy(tmp_path, **updates)

    result = invoke(
        root,
        answers(tmp_path),
        run_id="hook-invalid",
        extra_args=("--hook-policy-file", str(policy_path)),
    )

    assert result.exit_code == 2
    assert error in result.output
    assert project_files(root) == {}


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
    requirements_path = root / ".ai-project/capability-requirements.yaml"
    assert requirements_path.is_file()
    requirements_payload = yaml.safe_load(requirements_path.read_text(encoding="utf-8"))
    assert requirements_payload["schema_version"] == "1"
    quality_gates = next(
        item
        for item in requirements_payload["requirements"]
        if item["capability"] == "quality.gates"
    )
    assert quality_gates["reasons"]
    assert quality_gates["verification"]
    assert quality_gates["selected_provider"] is None
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


def test_init_binds_selected_user_skill_and_repeat_apply_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    home = tmp_path / "home"
    skill = home / ".agents/skills/formatter"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: formatter\ndescription: quality.gates\n---\nInstructions\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    unrelated = root / ".agents/skills/user-notes.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep me\n", encoding="utf-8")
    answer_path = answers(tmp_path)

    first = invoke(root, answer_path, run_id="bind-one")

    assert first.exit_code == 0, first.output
    bound = root / ".agents/skills/formatter/SKILL.md"
    assert bound.is_file(), first.output
    assert bound.read_text(encoding="utf-8").startswith("---\nname: formatter")
    assert unrelated.read_text(encoding="utf-8") == "keep me\n"
    before = project_files(root)

    second = invoke(root, answer_path, run_id="bind-two")

    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["applied_paths"] == []
    assert project_files(root) == before


def test_project_changeset_preserves_explicit_empty_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blueprint, resolution, inventory = inputs()

    def unexpected_plan_build(*args: object, **kwargs: object) -> None:
        raise AssertionError("explicit requirements must not rebuild the project plan")

    monkeypatch.setattr(init_module, "build_project_plan", unexpected_plan_build)

    changeset = _project_changeset(
        tmp_path,
        blueprint,
        inventory=inventory,
        resolution=resolution,
        requirements=(),
    )
    operation = next(
        item
        for item in changeset.operations
        if item.path == ".ai-project/capability-requirements.yaml"
    )
    assert yaml.safe_load(operation.after_content or "")["requirements"] == []


def test_project_changeset_replaces_partial_plan_inputs_with_one_coherent_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blueprint, resolution, inventory = inputs()
    inconsistent_inventory = replace(
        inventory, inventory_digest="inconsistent-inventory-digest"
    )
    plan = SimpleNamespace(
        inventory=inventory,
        resolution=resolution,
        requirements=requirements(),
    )
    monkeypatch.setattr(init_module, "build_project_plan", lambda *args, **kwargs: plan)

    changeset = _project_changeset(
        tmp_path,
        blueprint,
        inventory=inconsistent_inventory,
        resolution=None,
        requirements=(),
    )

    lock_operation = next(
        item
        for item in changeset.operations
        if item.path == ".ai-project/capabilities.lock"
    )
    lock = yaml.safe_load(lock_operation.after_content or "")
    assert lock["inventory_digest"] == inventory.inventory_digest


def test_init_removes_only_exact_obsolete_project_development_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    legacy_root = root / ".agents/skills/project-development"
    legacy_files = (
        legacy_root / "SKILL.md",
        legacy_root / "references/capability-routing.md",
        legacy_root / "references/quality-gates.md",
    )
    for path in legacy_files[1:]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("legacy generated content\n", encoding="utf-8")
    legacy_files[0].write_text(
        "---\n"
        "name: project-development\n"
        "description: Legacy generated project guidance.\n"
        "version: 1.0.0\n"
        "---\n\n"
        "# Legacy project development\n\n"
        "- Read [routing](references/capability-routing.md).\n"
        "- Read [quality gates](references/quality-gates.md).\n",
        encoding="utf-8",
    )
    user_file = legacy_root / "notes.md"
    user_file.write_text("keep user content\n", encoding="utf-8")

    result = invoke(root, answers(tmp_path), run_id="legacy-migration")

    assert result.exit_code == 0, result.output
    assert all(not path.exists() for path in legacy_files)
    assert user_file.read_text(encoding="utf-8") == "keep user content\n"

    second = invoke(root, answers(tmp_path), run_id="legacy-migration-two")

    assert second.exit_code == 0, second.output
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


def test_init_reports_not_requested_instead_of_claiming_empty_search(tmp_path: Path) -> None:
    root = tmp_path / "web-no-discovery"
    root.mkdir()
    answer_path = tmp_path / "web-no-discovery.json"
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

    result = invoke(root, answer_path, run_id="not-requested", dry_run=True)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    browser = next(
        item
        for item in payload["discovery"]
        if item["requirement"] == "browser.validation"
    )
    assert browser["status"] == "not-requested"
    assert browser["attempted_sources"] == []


def test_legacy_remote_snapshot_is_reported_as_cached_discovery(tmp_path: Path) -> None:
    root = tmp_path / "web-cached"
    root.mkdir()
    remote_snapshot(root)
    answer_path = tmp_path / "web-cached.json"
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

    result = invoke(
        root,
        answer_path,
        run_id="cached-discovery",
        dry_run=True,
        extra_args=("--remote-discovery",),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    browser = next(
        item
        for item in payload["discovery"]
        if item["requirement"] == "browser.validation"
    )
    assert browser["status"] == "candidates-found"
    assert browser["diagnostics"][0]["status"] == "cached"


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
