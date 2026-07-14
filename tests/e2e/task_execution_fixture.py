from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import yaml
from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from vibe.compiler.context import CapabilityCandidate, ContextSource, SourceKind
from vibe.compiler.intent import TaskIntent
from vibe.doctor.checks import DoctorContext, OutcomeInsightsCheck
from vibe.doctor.report import DoctorFinding
from vibe.inventory.service import InventoryResult
from vibe.materialize.templates import CapabilityLock, CapabilityLockEntry
from vibe.models.outcome import TaskOutcome
from vibe.models.risk import (
    DataSensitivity,
    Reversibility,
    ScopeLevel,
    TaskOperation,
)
from vibe.models.task import TaskPhase, TaskPlan
from vibe.persistence.database import create_sqlite_engine, migration_config
from vibe.persistence.repositories import TaskOutcomeRepository
from vibe.workflows.scenarios import ScenarioId, ScenarioRequest, classify_scenario
from vibe.workflows.task_graph import build_task_plan
from vibe.workflows.task_runner import PhaseExecutionResult, TaskRunCheckpoint, TaskRunner


class FakeTaskAppServer:
    def __init__(
        self,
        plan: TaskPlan,
        *,
        invalidate_after_phase: str | None,
        invalidate: Callable[[], None],
    ) -> None:
        self._conditions = {
            phase.phase_id: phase.completion_conditions for phase in plan.phases
        }
        self._invalidate_after_phase = invalidate_after_phase
        self._invalidate = invalidate
        self.prompts: list[str] = []
        self.resumed: list[str] = []

    async def start_thread(self, root: Path) -> str:
        return "thread-e2e-129"

    async def resume_thread(self, thread_id: str) -> str:
        self.resumed.append(thread_id)
        return thread_id

    async def execute_phase(self, thread_id: str, prompt: str) -> PhaseExecutionResult:
        assert thread_id == "thread-e2e-129"
        self.prompts.append(prompt)
        phase_id = json.loads(prompt)["context_capsule"]["current_phase"]
        if phase_id == self._invalidate_after_phase:
            self._invalidate()
            self._invalidate_after_phase = None
        return PhaseExecutionResult(
            phase_id=phase_id,
            completed=True,
            completion_evidence=(f"{phase_id} verified",),
            completion_conditions_met=self._conditions[phase_id],
            confirmed_facts=(f"confirmed:{phase_id}",),
            capabilities_used=("cap.used",),
        )


class TaskExecutionFixture:
    task_id = "e2e-payment-bug"

    def __init__(
        self, root: Path, *, invalidate_after_phase: str | None = None
    ) -> None:
        self.root = root
        self.database = root / "state.sqlite3"
        self.checkpoint = root / "task-checkpoint.json"
        self._head = "head-1"
        self.approval_requests: list[str] = []
        command.upgrade(migration_config(self.database), "head")
        factory = sessionmaker(
            create_sqlite_engine(self.database),
            class_=Session,
            expire_on_commit=False,
        )
        self.repository = TaskOutcomeRepository(factory)
        self.intent, self.plan = self._build_plan()
        self.app_server = FakeTaskAppServer(
            self.plan,
            invalidate_after_phase=invalidate_after_phase,
            invalidate=self._invalidate,
        )
        self._write_capability_lock()

    @property
    def executed_phase_ids(self) -> list[str]:
        return [
            json.loads(prompt)["context_capsule"]["current_phase"]
            for prompt in self.app_server.prompts
        ]

    def seed_history(self, *, count: int) -> None:
        for index in range(1, count + 1):
            self.repository.record(
                f"history-{index}",
                TaskOutcome(
                    task_type="bug",
                    workflow="rigorous",
                    capabilities_used=("cap.used",),
                    verification_passed=True,
                    user_rework=False,
                ),
            )

    def run(self, *, approve: bool, resume: bool = False) -> TaskRunCheckpoint:
        def approval_provider(phase: TaskPhase) -> bool:
            self.approval_requests.append(phase.phase_id)
            return approve

        runner = TaskRunner(
            root=self.root,
            app_server=self.app_server,
            checkpoint_path=self.checkpoint,
            head_provider=lambda: self._head,
            blueprint_digest_provider=lambda: "blueprint-1",
            approval_provider=approval_provider,
            outcome_recorder=self.repository.record,
        )
        candidates = tuple(
            CapabilityCandidate(
                capability_id="cap.used",
                provides=("task-execution",),
                phases=(phase.phase_id,),
            )
            for phase in self.plan.phases
        )
        return runner.run(
            self.intent,
            self.plan,
            candidates=candidates,
            sources=(
                ContextSource(
                    source_id="fixture-repository",
                    digest="fixture-repository-digest",
                    kind=SourceKind.REPOSITORY,
                ),
            ),
            user_scope_digest="fixture-scope-digest",
            resume=resume,
        )

    def recorded_outcome(self) -> TaskOutcome:
        return self.repository.get(self.task_id).outcome

    def outcome_exists(self) -> bool:
        try:
            self.repository.get(self.task_id)
        except LookupError:
            return False
        return True

    def unused_capability_finding(self) -> DoctorFinding:
        context = DoctorContext(
            root=self.root,
            inventory=InventoryResult(
                capabilities=(), diagnostics=(), inventory_digest="empty"
            ),
            command_resolver=lambda command_name: command_name,
        )
        return next(
            finding
            for finding in OutcomeInsightsCheck(self.database).check(context)
            if finding.code == "outcome.capability-unused"
        )

    def _invalidate(self) -> None:
        self._head = "head-2"

    def _build_plan(self) -> tuple[TaskIntent, TaskPlan]:
        classification = classify_scenario(
            ScenarioRequest(
                scenario=ScenarioId.BUG,
                scope=ScopeLevel.LOCAL,
                data_sensitivity=DataSensitivity.SENSITIVE,
                reversibility=Reversibility.REVERSIBLE,
                operations=frozenset(
                    {TaskOperation.WRITE_PROJECT, TaskOperation.HANDLE_PAYMENT}
                ),
            )
        )
        intent = TaskIntent(
            task_id=self.task_id,
            summary="Fix duplicate payment capture",
            scenario=ScenarioId.BUG,
            scope=("src/payments.py",),
            acceptance_criteria=("Duplicate capture is prevented and verified.",),
        )
        plan = build_task_plan(
            self.task_id,
            intent.summary,
            classification,
            acceptance_criteria=intent.acceptance_criteria,
            capabilities={
                phase_id: ("cap.used",)
                for phase_id in (
                    "inspect",
                    "design",
                    "approval",
                    "rollback",
                    "implement",
                    "verify",
                    "review",
                )
            },
        )
        return intent, plan

    def _write_capability_lock(self) -> None:
        lock = CapabilityLock(
            inventory_digest="inventory-digest",
            providers=tuple(
                CapabilityLockEntry(
                    provider_id=provider_id,
                    kind="agent-skill",
                    scope="project",
                    source=provider_id,
                    content_digest="digest-1234",
                )
                for provider_id in ("cap.used", "cap.unused")
            ),
        )
        target = self.root / ".ai-project" / "capabilities.lock"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            yaml.safe_dump(lock.model_dump(mode="json"), sort_keys=True),
            encoding="utf-8",
        )
