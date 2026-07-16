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
from vibe.models.capability import CapabilityScope

_FRONTMATTER = re.compile(
    r"\A---\s*\r?\n(?P<header>.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL
)
_PROMPT_CAPABILITIES = {
    "browser": "browser.validation",
    "checkout": "browser.validation",
    "fix": "quality.gates",
    "failure": "quality.gates",
    "login": "quality.gates",
}


@dataclass(frozen=True)
class InstalledHook:
    hooks: dict[str, Any]
    trust_digest: str


class CodexNativeSession:
    """Small fake host that selects only from native Skill descriptions."""

    def __init__(self, project: CodexNativeProjectFixture) -> None:
        self._project = project
        self.thread_id = "thread-codex-native-1"
        self.loaded_skill_paths: list[Path] = []
        self.internal_commands: list[str] = []
        self._pending_capability: str | None = None
        self.app_server_process_starts = 0
        self.app_server_thread_starts = 0
        self._start_task_process()
        self._start_task_thread()

    @property
    def loaded_skill_names(self) -> tuple[str, ...]:
        return tuple(path.parent.name for path in self.loaded_skill_paths)

    @property
    def started_nested_codex_processes(self) -> int:
        return self.app_server_process_starts - 1

    @property
    def started_nested_codex_threads(self) -> int:
        return self.app_server_thread_starts - 1

    def request(self, prompt: str) -> None:
        required = self._required_description(prompt)
        match = self._matching_skill(required)
        if match is not None:
            self._load(match)
            return
        self._pending_capability = required
        manager = self._project.root / ".agents/skills/project-capability-manager/SKILL.md"
        self._load(manager)

    def approve_project_candidate(self, name: str) -> None:
        if self._pending_capability is None:
            raise AssertionError("no capability gap is awaiting approval")
        bundle = self._project.root / ".scenario/registry" / f"{name}.json"
        result = self._project.runner.invoke(
            app,
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
        installed = self._matching_skill(self._pending_capability)
        if installed is None:
            raise AssertionError("approved candidate did not satisfy the pending capability")
        self._load(installed)
        self._pending_capability = None

    def _required_description(self, prompt: str) -> str:
        words = set(re.findall(r"[a-z]+", prompt.lower()))
        matches = {
            description
            for word, description in _PROMPT_CAPABILITIES.items()
            if word in words
        }
        if len(matches) != 1:
            raise AssertionError(
                f"fixture prompt must identify one capability description: {prompt}"
            )
        return matches.pop()

    def _matching_skill(self, required: str) -> Path | None:
        for path, description in self._project.discoverable_skills():
            if description == required:
                return path
        return None

    def _load(self, path: Path) -> None:
        if path not in self.loaded_skill_paths:
            self.loaded_skill_paths.append(path)

    def _start_task_process(self) -> None:
        self.app_server_process_starts += 1
        if self.app_server_process_starts > 1:
            raise AssertionError("native task attempted to start a nested Codex process")

    def _start_task_thread(self) -> None:
        self.app_server_thread_starts += 1
        if self.app_server_thread_starts > 1:
            raise AssertionError("native task attempted to start a nested Codex thread")


class CodexNativeProjectFixture:
    def __init__(self, root: Path, codex_home: Path) -> None:
        self.root = root
        self.codex_home = codex_home
        self.runner = CliRunner()
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
        return self.runner.invoke(
            app,
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

    def discoverable_skills(self) -> tuple[tuple[Path, str], ...]:
        found = []
        for path in sorted((self.root / ".agents/skills").glob("*/SKILL.md")):
            metadata = _skill_metadata(path)
            found.append((path, str(metadata["description"])))
        return tuple(found)

    def discoverable_skill_names(self) -> tuple[str, ...]:
        return tuple(path.parent.name for path, _ in self.discoverable_skills())

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
        return InstalledHook(
            hooks=json.loads((self.root / ".codex/hooks.json").read_text(encoding="utf-8")),
            trust_digest=rendered.trust_digest,
        )

    def installed_hook_trust_digest(self) -> str:
        hooks = (self.root / ".codex/hooks.json").read_bytes()
        script_path = ".ai-project/hooks/governance.py"
        script = (self.root / script_path).read_bytes()
        return combined_hook_trust_digest(hooks, script_path, script)

    def _install_user_skill(self, name: str) -> None:
        skill = self.codex_home / "skills" / name
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: quality.gates\n---\n\n"
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


@pytest.fixture
def native_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> CodexNativeProjectFixture:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    built = build_scenario("blank-web-remote", tmp_path / "project")
    return CodexNativeProjectFixture(built.root, codex_home)
