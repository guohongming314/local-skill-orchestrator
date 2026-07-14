"""Sequential, checkpointed execution of approved task plans against Codex."""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

import anyio
from pydantic import BaseModel, ConfigDict, Field

from vibe.compiler.context import (
    CapabilityCandidate,
    ContextSource,
    compile_context_capsule,
)
from vibe.compiler.intent import TaskIntent
from vibe.models.task import TaskPhase, TaskPlan


class TaskRunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting-approval"
    INVALIDATED = "invalidated"
    COMPLETED = "completed"
    FAILED = "failed"


class PhaseExecutionResult(BaseModel):
    """Structured evidence returned by Codex after executing one phase."""

    model_config = ConfigDict(frozen=True)

    phase_id: str = Field(min_length=1)
    completed: bool
    completion_evidence: tuple[str, ...] = ()
    completion_conditions_met: tuple[str, ...] = ()
    confirmed_facts: tuple[str, ...] = ()


class TaskRunCheckpoint(BaseModel):
    """Additive task execution state persisted at every control-plane boundary."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1"
    task_id: str
    status: TaskRunStatus
    codex_thread_id: str
    source_head: str
    blueprint_digest: str
    next_phase_index: int = 0
    next_phase_id: str | None = None
    completed_phase_ids: tuple[str, ...] = ()
    phase_results: tuple[PhaseExecutionResult, ...] = ()
    confirmed_facts: tuple[str, ...] = ()
    error: str | None = None


class TaskAppServer(Protocol):
    """Execution-plane operations needed by the task control plane."""

    async def start_thread(self, root: Path) -> str: ...

    async def resume_thread(self, thread_id: str) -> str: ...

    async def execute_phase(self, thread_id: str, prompt: str) -> PhaseExecutionResult: ...


class TaskRunner:
    """Advance one task phase at a time, recompiling context at each transition."""

    def __init__(
        self,
        *,
        root: Path,
        app_server: TaskAppServer,
        checkpoint_path: Path,
        head_provider: Callable[[], str],
        blueprint_digest_provider: Callable[[], str],
        approval_provider: Callable[[TaskPhase], bool],
    ) -> None:
        self.root = root.resolve()
        self.app_server = app_server
        self.checkpoint_path = checkpoint_path.resolve()
        self.head_provider = head_provider
        self.blueprint_digest_provider = blueprint_digest_provider
        self.approval_provider = approval_provider

    def run(
        self,
        intent: TaskIntent,
        plan: TaskPlan,
        *,
        candidates: tuple[CapabilityCandidate, ...],
        sources: tuple[ContextSource, ...],
        user_scope_digest: str,
        resume: bool = False,
    ) -> TaskRunCheckpoint:
        """Run until completion or a durable approval/invalidation boundary."""
        if intent.task_id != plan.task_id:
            raise ValueError("intent and plan task_id values must match")
        return anyio.run(
            self._run,
            intent,
            plan,
            candidates,
            sources,
            user_scope_digest,
            resume,
        )

    async def _run(
        self,
        intent: TaskIntent,
        plan: TaskPlan,
        candidates: tuple[CapabilityCandidate, ...],
        sources: tuple[ContextSource, ...],
        user_scope_digest: str,
        resume: bool,
    ) -> TaskRunCheckpoint:
        try:
            return await self._run_open(
                intent, plan, candidates, sources, user_scope_digest, resume
            )
        finally:
            close = getattr(self.app_server, "close", None)
            if close is not None:
                await close()

    async def _run_open(
        self,
        intent: TaskIntent,
        plan: TaskPlan,
        candidates: tuple[CapabilityCandidate, ...],
        sources: tuple[ContextSource, ...],
        user_scope_digest: str,
        resume: bool,
    ) -> TaskRunCheckpoint:
        current_head = self.head_provider()
        current_blueprint = self.blueprint_digest_provider()
        if resume:
            checkpoint = self._load()
            if checkpoint.task_id != plan.task_id:
                raise ValueError("checkpoint task_id does not match the task plan")
            thread_id = await self.app_server.resume_thread(checkpoint.codex_thread_id)
            checkpoint = checkpoint.model_copy(
                update={
                    "status": TaskRunStatus.RUNNING,
                    "codex_thread_id": thread_id,
                    "source_head": current_head,
                    "blueprint_digest": current_blueprint,
                    "error": None,
                }
            )
        else:
            thread_id = await self.app_server.start_thread(self.root)
            checkpoint = TaskRunCheckpoint(
                task_id=plan.task_id,
                status=TaskRunStatus.RUNNING,
                codex_thread_id=thread_id,
                source_head=current_head,
                blueprint_digest=current_blueprint,
                next_phase_id=plan.phases[0].phase_id,
            )
        self._save(checkpoint)

        for index in range(checkpoint.next_phase_index, len(plan.phases)):
            phase = plan.phases[index]
            live_head = self.head_provider()
            live_blueprint = self.blueprint_digest_provider()
            if live_head != checkpoint.source_head or live_blueprint != checkpoint.blueprint_digest:
                return self._pause(
                    checkpoint,
                    status=TaskRunStatus.INVALIDATED,
                    next_phase_index=index,
                    next_phase_id=phase.phase_id,
                    error=(
                        "Context inputs changed; resume to recompile from the durable checkpoint."
                    ),
                )
            if phase.requires_approval and not self.approval_provider(phase):
                return self._pause(
                    checkpoint,
                    status=TaskRunStatus.AWAITING_APPROVAL,
                    next_phase_index=index,
                    next_phase_id=phase.phase_id,
                )

            capsule = compile_context_capsule(
                intent,
                plan,
                phase=phase.phase_id,
                candidates=candidates,
                sources=sources,
                head=live_head,
                user_scope_digest=user_scope_digest,
            )
            prompt = self._phase_prompt(capsule.model_dump(mode="json"), checkpoint, candidates)
            result = await self.app_server.execute_phase(thread_id, prompt)
            self._verify_phase(phase, result)
            confirmed = tuple(dict.fromkeys((*checkpoint.confirmed_facts, *result.confirmed_facts)))
            completed = (*checkpoint.completed_phase_ids, phase.phase_id)
            results = (*checkpoint.phase_results, result)
            next_index = index + 1
            checkpoint = checkpoint.model_copy(
                update={
                    "completed_phase_ids": completed,
                    "phase_results": results,
                    "confirmed_facts": confirmed,
                    "next_phase_index": next_index,
                    "next_phase_id": (
                        plan.phases[next_index].phase_id if next_index < len(plan.phases) else None
                    ),
                }
            )
            self._save(checkpoint)

        checkpoint = checkpoint.model_copy(update={"status": TaskRunStatus.COMPLETED})
        self._save(checkpoint)
        return checkpoint

    @staticmethod
    def _phase_prompt(
        capsule: dict[str, object],
        checkpoint: TaskRunCheckpoint,
        candidates: tuple[CapabilityCandidate, ...],
    ) -> str:
        selected = set(cast(list[str], capsule["selected_capability_ids"]))
        capability_content = {
            candidate.capability_id: list(candidate.provides)
            for candidate in candidates
            if candidate.capability_id in selected
        }
        return json.dumps(
            {
                "context_capsule": capsule,
                "confirmed_state": list(checkpoint.confirmed_facts),
                "capability_content": capability_content,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _verify_phase(phase: TaskPhase, result: PhaseExecutionResult) -> None:
        if result.phase_id != phase.phase_id:
            raise RuntimeError(
                f"Codex returned phase {result.phase_id!r} while executing {phase.phase_id!r}"
            )
        missing = set(phase.completion_conditions) - set(result.completion_conditions_met)
        if not result.completed or missing:
            detail = ", ".join(sorted(missing)) or "phase marked incomplete"
            raise RuntimeError(f"phase {phase.phase_id!r} did not complete: {detail}")

    def _pause(
        self,
        checkpoint: TaskRunCheckpoint,
        *,
        status: TaskRunStatus,
        next_phase_index: int,
        next_phase_id: str,
        error: str | None = None,
    ) -> TaskRunCheckpoint:
        paused = checkpoint.model_copy(
            update={
                "status": status,
                "next_phase_index": next_phase_index,
                "next_phase_id": next_phase_id,
                "error": error,
            }
        )
        self._save(paused)
        return paused

    def _save(self, checkpoint: TaskRunCheckpoint) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.checkpoint_path.with_suffix(self.checkpoint_path.suffix + ".tmp")
        temporary.write_text(checkpoint.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.checkpoint_path)

    def _load(self) -> TaskRunCheckpoint:
        if not self.checkpoint_path.is_file():
            raise FileNotFoundError(f"task checkpoint does not exist: {self.checkpoint_path}")
        return TaskRunCheckpoint.model_validate_json(
            self.checkpoint_path.read_text(encoding="utf-8")
        )
