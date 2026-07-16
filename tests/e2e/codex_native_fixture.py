"""Acceptance fixture for the Codex-native project capability experience."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, cast

import anyio
import pytest
import yaml
from typer.testing import CliRunner, Result

from tests.scenarios.builders import build_scenario
from vibe.cli import app
from vibe.codex.app_server import CodexAppServerClient
from vibe.codex.jsonrpc import JsonRpcSubprocessClient
from vibe.inventory.adapters.agent_skill import AgentSkillAdapter, SkillRoot
from vibe.materialize.project_hooks import combined_hook_trust_digest
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
class NativeSkillMetadata:
    path: Path
    name: str
    description: str


@dataclass
class ObservedCodexBoundaries:
    thread_ids: list[str]
    process_starts: int = 0
    thread_starts: int = 0

    async def reject_process_start(self, *_args: object, **_kwargs: object) -> None:
        self.process_starts += 1
        raise AssertionError("Vibe attempted to start a nested Codex process")

    async def reject_thread_start(self, *_args: object, **_kwargs: object) -> None:
        self.thread_starts += 1
        raise AssertionError("Vibe attempted to start a nested Codex thread")


class FakeCodexLifecycleHost:
    """Synchronous JSONL client for the repository's fake app-server lifecycle."""

    def __init__(self, state_path: Path, boundaries: ObservedCodexBoundaries) -> None:
        self.state_path = state_path
        self.boundaries = boundaries
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1

    def start(self, root: Path) -> str:
        if self._process is not None:
            raise AssertionError("fake Codex host is already started")
        script = Path(__file__).parents[1] / "fakes/fake_app_server.py"
        self._process = subprocess.Popen(
            [sys.executable, str(script), "lifecycle", str(self.state_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.boundaries.process_starts += 1
        self._request(
            "initialize",
            {"clientInfo": {"name": "native-acceptance", "version": "1"}},
        )
        self._write({"method": "initialized"})
        result = self._request("thread/start", {"cwd": str(root.resolve())})
        notification = self._read()
        if notification.get("method") != "thread/started":
            raise AssertionError("fake Codex host did not emit thread/started")
        thread_id = str(result["thread"]["id"])
        observed = str(notification["params"]["thread"]["id"])
        if observed != thread_id:
            raise AssertionError("thread/start response and notification disagree")
        self.boundaries.thread_ids.append(thread_id)
        self.boundaries.thread_starts += 1
        return thread_id

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        self._process = None

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write({"id": request_id, "method": method, "params": params})
        while True:
            message = self._read()
            if message.get("id") == request_id:
                result = message.get("result")
                if not isinstance(result, dict):
                    raise AssertionError(f"fake Codex {method} returned no object result")
                return result

    def _write(self, message: dict[str, Any]) -> None:
        stream = self._stdin()
        stream.write(json.dumps(message, separators=(",", ":")) + "\n")
        stream.flush()

    def _read(self) -> dict[str, Any]:
        line = self._stdout().readline()
        if not line:
            stderr = self._process.stderr.read() if self._process and self._process.stderr else ""
            raise AssertionError(f"fake Codex host closed unexpectedly: {stderr}")
        message = json.loads(line)
        if not isinstance(message, dict):
            raise AssertionError("fake Codex host emitted a non-object message")
        return cast(dict[str, Any], message)

    def _stdin(self) -> IO[str]:
        if self._process is None or self._process.stdin is None:
            raise AssertionError("fake Codex host stdin is unavailable")
        return self._process.stdin

    def _stdout(self) -> IO[str]:
        if self._process is None or self._process.stdout is None:
            raise AssertionError("fake Codex host stdout is unavailable")
        return self._process.stdout


class CodexNativeSession:
    """Small fake host that selects only from native Skill descriptions."""

    def __init__(self, project: CodexNativeProjectFixture) -> None:
        self._project = project
        self.thread_id = project.codex_boundaries.thread_ids[-1]
        self.agents_md = (project.root / "AGENTS.md").read_text(encoding="utf-8")
        self.discovered_skills = project.discoverable_skills()
        hooks_path = project.root / ".codex/hooks.json"
        hooks = json.loads(hooks_path.read_text(encoding="utf-8")) if hooks_path.is_file() else {}
        configured = hooks.get("hooks", {})
        self.configured_hook_events = (
            tuple(sorted(configured)) if isinstance(configured, dict) else ()
        )
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
        return self._project.codex_boundaries.process_starts - 1

    @property
    def started_nested_codex_threads(self) -> int:
        return self._project.codex_boundaries.thread_starts - 1

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
        reference = (
            self._project.root
            / ".agents/skills/project-capability-manager/references/governance-commands.md"
        ).read_text(encoding="utf-8")
        documented = (
            "vibe install <name> --path <root> --candidate-file <bundle> --approve"
        )
        if f"`{documented}`" not in reference:
            raise AssertionError("generated manager does not document the install contract")
        command = documented.replace("<name>", name).replace(
            "<root>", str(self._project.root)
        ).replace("<bundle>", str(bundle))
        argv = shlex.split(command)
        if argv[0] != "vibe":
            raise AssertionError("documented install contract is not a vibe command")
        result = self._project._invoke_vibe(argv[1:])
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
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self.root = root
        self.codex_home = codex_home
        self.codex_boundaries = codex_boundaries
        self._monkeypatch = monkeypatch
        self._host = FakeCodexLifecycleHost(root.parent / "fake-codex-state.json", codex_boundaries)
        self._guards_installed = False
        self.runner = CliRunner()
        self.vibe_invocations: list[tuple[str, ...]] = []
        self._run_number = 0

    def initialize(self, *, selected_skill: str, approved_hook: bool = False) -> Result:
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
        arguments = [
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
        ]
        if approved_hook:
            policy = self.root.parent / f"native-hook-policy-{self._run_number}.json"
            policy.write_text(
                json.dumps(
                    {
                        "events": ["PreToolUse", "Stop"],
                        "script_path": ".ai-project/hooks/governance.py",
                        "script_content": "print('governance')\n",
                        "permissions": ["execute-command"],
                        "approved": True,
                        "approval_provenance": "acceptance:attended-review",
                    }
                ),
                encoding="utf-8",
            )
            arguments.extend(("--hook-policy-file", str(policy)))
        return self._invoke_vibe(arguments)

    def start_session(self) -> CodexNativeSession:
        if not (self.root / "AGENTS.md").is_file():
            raise AssertionError("project must be initialized before starting Codex")
        if not self.codex_boundaries.thread_ids:
            self._host.start(self.root)
        self._install_nested_start_guards()
        return CodexNativeSession(self)

    @property
    def observed_process_starts(self) -> int:
        return self.codex_boundaries.process_starts

    @property
    def observed_thread_starts(self) -> int:
        return self.codex_boundaries.thread_starts

    def fake_host_state(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(self._host.state_path.read_text(encoding="utf-8")),
        )

    def close(self) -> None:
        self._host.close()

    def attempt_nested_process_start(self) -> None:
        client = JsonRpcSubprocessClient(("codex", "app-server"))
        anyio.run(client.start)

    def attempt_nested_thread_start(self) -> None:
        client = CodexAppServerClient(cast(Any, object()))

        async def start() -> None:
            await client.start_thread(cwd=self.root)

        anyio.run(start)

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

    def invoke_internal(self, arguments: list[str]) -> Result:
        return self._invoke_vibe(arguments)

    def _install_nested_start_guards(self) -> None:
        if self._guards_installed:
            return
        self._monkeypatch.setattr(
            "vibe.codex.jsonrpc.anyio.open_process",
            self.codex_boundaries.reject_process_start,
        )
        self._monkeypatch.setattr(
            "vibe.codex.app_server.CodexAppServerClient.start_thread",
            self.codex_boundaries.reject_thread_start,
        )
        self._guards_installed = True

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
) -> Iterator[CodexNativeProjectFixture]:
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    boundaries = ObservedCodexBoundaries(thread_ids=[])
    built = build_scenario("blank-web-remote", tmp_path / "project")
    fixture = CodexNativeProjectFixture(built.root, codex_home, boundaries, monkeypatch)
    try:
        yield fixture
    finally:
        fixture.close()
