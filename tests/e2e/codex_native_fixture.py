"""Acceptance fixture for the Codex-native project capability experience."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from tests.scenarios.builders import build_scenario
from vibe.cli import app
from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.materialize.project_hooks import (
    ProjectHookPolicy,
    combined_hook_trust_digest,
    render_project_hooks,
)
from vibe.materialize.templates import CapabilityLock, CapabilityLockEntry
from vibe.models.capability import CapabilityScope

_FRONTMATTER = re.compile(
    r"\A---\s*\r?\n(?P<header>.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "do",
        "for",
        "is",
        "it",
        "of",
        "or",
        "the",
        "to",
        "use",
        "when",
        "with",
    }
)


@dataclass(frozen=True)
class InstalledHook:
    hooks: dict[str, Any]
    trust_digest: str


@dataclass(frozen=True)
class NativeSkillMetadata:
    path: Path
    name: str
    description: str


@dataclass
class ObservedCodexBoundaries:
    thread_ids: list[str]
    nested_process_starts: int = 0
    nested_thread_starts: int = 0

    async def reject_process_start(self, *_args: object, **_kwargs: object) -> None:
        self.nested_process_starts += 1
        raise AssertionError("Vibe attempted to start a nested Codex process")

    async def reject_thread_start(self, *_args: object, **_kwargs: object) -> None:
        self.nested_thread_starts += 1
        raise AssertionError("Vibe attempted to start a nested Codex thread")


class CodexNativeSession:
    """Small fake host that selects only from native Skill descriptions."""

    def __init__(self, project: CodexNativeProjectFixture) -> None:
        self._project = project
        self.thread_id = project.codex_boundaries.thread_ids[-1]
        self.agents_md = (project.root / "AGENTS.md").read_text(encoding="utf-8")
        self.discovered_skills = project.discoverable_skills()
        self.loaded_skill_paths: list[Path] = []
        self._pending_capability: str | None = None

    @property
    def internal_commands(self) -> tuple[str, ...]:
        return tuple(arguments[0] for arguments in self._project.vibe_invocations)

    @property
    def observed_thread_ids(self) -> tuple[str, ...]:
        return tuple(self._project.codex_boundaries.thread_ids)

    @property
    def loaded_skill_names(self) -> tuple[str, ...]:
        return tuple(path.parent.name for path in self.loaded_skill_paths)

    @property
    def started_nested_codex_processes(self) -> int:
        return self._project.codex_boundaries.nested_process_starts

    @property
    def started_nested_codex_threads(self) -> int:
        return self._project.codex_boundaries.nested_thread_starts

    def request(self, prompt: str) -> None:
        match = _select_native_skill(prompt, self.discovered_skills)
        if match is not None:
            self._load(match.path)
            return
        self._pending_capability = prompt
        manager = self._project.root / ".agents/skills/project-capability-manager/SKILL.md"
        self._load(manager)

    def approve_project_candidate(self, name: str) -> None:
        if self._pending_capability is None:
            raise AssertionError("no capability gap is awaiting approval")
        bundle = self._project.root / ".scenario/registry" / f"{name}.json"
        result = self._project._invoke_vibe(
            [
                "install",
                name,
                "--path",
                str(self._project.root),
                "--candidate-file",
                str(bundle),
                "--approve",
            ],
        )
        assert result.exit_code == 0, result.output
        self.discovered_skills = self._project.discoverable_skills()
        installed = _select_native_skill(self._pending_capability, self.discovered_skills)
        if installed is None:
            raise AssertionError("approved candidate did not satisfy the pending capability")
        self._load(installed.path)
        self._pending_capability = None

    def _load(self, path: Path) -> None:
        if path not in self.loaded_skill_paths:
            self.loaded_skill_paths.append(path)


class CodexNativeProjectFixture:
    def __init__(
        self,
        root: Path,
        codex_home: Path,
        codex_boundaries: ObservedCodexBoundaries,
    ) -> None:
        self.root = root
        self.codex_home = codex_home
        self.codex_boundaries = codex_boundaries
        self.runner = CliRunner()
        self.vibe_invocations: list[tuple[str, ...]] = []
        self._run_number = 0

    def initialize(self, *, selected_skill: str) -> Result:
        self._install_user_skill(selected_skill)
        self._run_number += 1
        answers = self.root.parent / f"native-answers-{self._run_number}.json"
        answers.write_text(
            json.dumps(
                {
                    "goal": "Build and validate a web application",
                    "lifecycle_stage": "active-development",
                    "risk_level": "medium",
                    "project_type": "web-application",
                }
            ),
            encoding="utf-8",
        )
        return self._invoke_vibe(
            [
                "init",
                "--path",
                str(self.root),
                "--run-id",
                f"native-init-{self._run_number}",
                "--checkpoints",
                str(self.root.parent / f"native-init-{self._run_number}.sqlite3"),
                "--answers",
                str(answers),
                "--confirm",
                "--remote-discovery",
                "--json",
            ],
        )

    def start_session(self) -> CodexNativeSession:
        if not (self.root / "AGENTS.md").is_file():
            raise AssertionError("project must be initialized before starting Codex")
        return CodexNativeSession(self)

    def discoverable_skills(self) -> tuple[NativeSkillMetadata, ...]:
        found: list[NativeSkillMetadata] = []
        for path in sorted((self.root / ".agents/skills").glob("*/SKILL.md")):
            metadata = _skill_metadata(path)
            found.append(
                NativeSkillMetadata(
                    path=path,
                    name=str(metadata["name"]),
                    description=str(metadata["description"]),
                )
            )
        return tuple(found)

    def discoverable_skill_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.discoverable_skills())

    def skill_metadata(self, path: Path) -> dict[str, Any]:
        return _skill_metadata(path)

    def skill_metadata_is_valid(self, path: Path) -> bool:
        adapter = AgentSkillAdapter(
            roots=(SkillRoot(path.parent.parent, CapabilityScope.PROJECT),)
        )
        discovery = next(
            item for item in adapter.discover() if Path(item.locator).resolve() == path.resolve()
        )
        result = adapter.scan(discovery)
        return result.verification.verified and result.manifest.name == path.parent.name

    def install_approved_hook(self) -> InstalledHook:
        policy = ProjectHookPolicy(
            events=("PreToolUse", "Stop"),
            script_path=".ai-project/hooks/governance.py",
            script_content="print('governance')\n",
            approved=True,
            approval_provenance="acceptance:attended-review",
        )
        rendered = render_project_hooks(policy)
        for item in rendered.files:
            target = self.root / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item.content, encoding="utf-8")
        assert rendered.trust_digest is not None
        assert rendered.content_digest is not None
        assert rendered.script_digest is not None
        lock_path = self.root / ".ai-project/capabilities.lock"
        lock = CapabilityLock.model_validate(
            yaml.safe_load(lock_path.read_text(encoding="utf-8"))
        )
        hook = CapabilityLockEntry(
            provider_id="hook.project",
            kind="hook",
            scope="project",
            source=".codex/hooks.json",
            content_digest=rendered.content_digest,
            hook_approved=True,
            hook_approval_provenance=policy.approval_provenance,
            hook_trust_digest=rendered.trust_digest,
            hook_events=tuple(sorted(policy.events)),
            hook_permissions=tuple(sorted(policy.permissions)),
            hook_script_path=policy.script_path,
            hook_script_digest=rendered.script_digest,
        )
        updated = lock.model_copy(update={"providers": (*lock.providers, hook)})
        lock_path.write_text(
            yaml.safe_dump(updated.model_dump(mode="json"), sort_keys=True),
            encoding="utf-8",
        )
        return InstalledHook(
            hooks=json.loads((self.root / ".codex/hooks.json").read_text(encoding="utf-8")),
            trust_digest=rendered.trust_digest,
        )

    def installed_hook_trust_digest(self) -> str:
        hooks = (self.root / ".codex/hooks.json").read_bytes()
        script_path = ".ai-project/hooks/governance.py"
        script = (self.root / script_path).read_bytes()
        return combined_hook_trust_digest(hooks, script_path, script)

    def hook_lock_entry(self) -> dict[str, Any]:
        lock = yaml.safe_load(
            (self.root / ".ai-project/capabilities.lock").read_text(encoding="utf-8")
        )
        return next(
            item for item in lock["providers"] if item["provider_id"] == "hook.project"
        )

    def _invoke_vibe(self, arguments: list[str]) -> Result:
        self.vibe_invocations.append(tuple(arguments))
        return self.runner.invoke(app, arguments)

    def _install_user_skill(self, name: str) -> None:
        skill = self.codex_home / "skills" / name
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\n"
            "description: Diagnose intermittent failures and verify bug fixes\n"
            "provides: quality.gates\n---\n\n"
            "Diagnose failures systematically and verify the fix.\n",
            encoding="utf-8",
        )
        metadata = skill / "agents/openai.yaml"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(
            "interface:\n"
            f"  display_name: {name}\n"
            "  short_description: Systematic debugging and verification\n"
            "policy:\n"
            "  allow_implicit_invocation: true\n",
            encoding="utf-8",
        )


def _skill_metadata(path: Path) -> dict[str, Any]:
    match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if match is None:
        raise AssertionError(f"missing Skill frontmatter: {path}")
    payload = yaml.safe_load(match.group("header"))
    if not isinstance(payload, dict):
        raise AssertionError(f"invalid Skill frontmatter: {path}")
    return payload


def _native_tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower())) - _STOPWORDS


def _select_native_skill(
    prompt: str, skills: tuple[NativeSkillMetadata, ...]
) -> NativeSkillMetadata | None:
    prompt_tokens = _native_tokens(prompt)
    scored = [
        (len(prompt_tokens & _native_tokens(skill.description)), skill)
        for skill in skills
    ]
    positive = [(score, skill) for score, skill in scored if score > 0]
    if not positive:
        return None
    highest = max(score for score, _skill in positive)
    matches = [skill for score, skill in positive if score == highest]
    return matches[0] if len(matches) == 1 else None


@pytest.fixture
def native_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> CodexNativeProjectFixture:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    boundaries = ObservedCodexBoundaries(thread_ids=["thread-codex-native-observed"])
    monkeypatch.setattr(
        "vibe.codex.jsonrpc.anyio.open_process", boundaries.reject_process_start
    )
    monkeypatch.setattr(
        "vibe.codex.app_server.CodexAppServerClient.start_thread",
        boundaries.reject_thread_start,
    )
    built = build_scenario("blank-web-remote", tmp_path / "project")
    return CodexNativeProjectFixture(built.root, codex_home, boundaries)
