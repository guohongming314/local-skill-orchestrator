"""Model-only project initialization command."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import anyio
import typer

from vibe.codex.exec_fallback import StructuredResultError as CodexStructuredResultError
from vibe.commands.inspect import _complete_snapshot
from vibe.commands.project_plan import build_project_plan, scan_project_inventory
from vibe.conversation.interview import InterviewInput, InterviewQuestion, build_interview
from vibe.conversation.prompts import QUESTION_ORDER
from vibe.conversation.runner import ConversationRunner
from vibe.conversation.structured_result import StructuredProjectResult, ValueSource
from vibe.inventory.service import InventoryResult
from vibe.materialize.agents_md import merge_agents_md
from vibe.materialize.capability_manager import render_agents_guidance
from vibe.materialize.changeset import (
    ChangeProposal,
    ChangeSet,
    CommandProposal,
    build_changeset,
    render_dry_run,
)
from vibe.materialize.ownership import FileOwnership
from vibe.materialize.templates import render_project_configuration
from vibe.materialize.writer import ApplyFailure, ConcurrentChangeError, apply_changeset
from vibe.models.blueprint import Blueprint
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot
from vibe.models.resolution import ResolutionPlan
from vibe.remote.models import RemoteCandidate
from vibe.remote.scoring import CandidateEvidence
from vibe.resolver.requirements import AbstractCapabilityRequirement
from vibe.workflows.checkpoints import CheckpointConflict, SqliteCheckpointStore
from vibe.workflows.init_graph import InitializationGraph, InvalidTransition
from vibe.workflows.state import InitCheckpoint, InitStage, InitStatus

APP_SERVER_COMMAND: tuple[str, ...] = ("codex", "app-server")


def init_command(
    model_only: Annotated[bool, typer.Option("--model-only")] = False,
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    run_id: Annotated[str, typer.Option("--run-id")] = "init",
    checkpoints: Annotated[Path | None, typer.Option("--checkpoints")] = None,
    answers: Annotated[Path | None, typer.Option("--answers", exists=True, dir_okay=False)] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    resume: Annotated[bool, typer.Option("--resume")] = False,
    confirm: Annotated[bool, typer.Option("--confirm")] = False,
    cancel: Annotated[bool, typer.Option("--cancel")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    git_init: Annotated[bool, typer.Option("--git-init")] = False,
    remote_discovery: Annotated[
        bool, typer.Option("--remote-discovery")
    ] = False,
    remote_decision: Annotated[
        list[str] | None, typer.Option("--remote-decision")
    ] = None,
) -> None:
    """Inspect, review, and optionally materialize project AI configuration."""
    if model_only and dry_run:
        typer.echo("--dry-run cannot be combined with --model-only", err=True)
        raise typer.Exit(2)
    root = (path or Path.cwd()).resolve()
    checkpoint_path = (checkpoints or root / ".vibe-init-checkpoints.sqlite3").resolve()
    output_path = (output or root / "blueprint.json").resolve()
    checkpoint_store = SqliteCheckpointStore(checkpoint_path)
    workflow = InitializationGraph(checkpoint_store)

    try:
        snapshot = _complete_snapshot(root)
        checkpoint = _open_run(
            workflow,
            run_id=run_id,
            repository_digest=snapshot.source_digest,
            resume=resume,
        )
        if cancel:
            cancelled = workflow.cancel(run_id, reason="user cancelled initialization")
            _emit({"run_id": run_id, "status": cancelled.status.value}, json_output)
            return

        if checkpoint.stage is InitStage.INSPECT:
            checkpoint = workflow.advance(
                run_id,
                InitStage.INVENTORY,
                confirmed={"repository": snapshot.model_dump(mode="json")},
            )
        inventory = scan_project_inventory(root)
        if checkpoint.stage is InitStage.INVENTORY:
            checkpoint = workflow.advance(
                run_id,
                InitStage.INTERVIEW,
                confirmed={
                    "inventory_summary": [
                        item.manifest.capability_id for item in inventory.capabilities
                    ]
                },
            )

        answer_payload = _load_answers(answers)
        conversation_result: StructuredProjectResult | None = None
        if checkpoint.stage is InitStage.INTERVIEW and answer_payload is None:
            interview = build_interview(
                InterviewInput(
                    repository=snapshot,
                    unknowns=_interview_unknowns(snapshot),
                    inventory_summary=tuple(
                        item.manifest.capability_id for item in inventory.capabilities
                    ),
                )
            )
            try:
                conversation_result = anyio.run(
                    partial(
                        ConversationRunner(app_server_command=APP_SERVER_COMMAND).run,
                        repository=snapshot,
                        interview=interview,
                        ask_user=_ask_interview_question,
                        checkpoint_store=checkpoint_store,
                        run_id=run_id,
                    )
                )
            except BaseExceptionGroup as exc:
                if not _contains_user_abort(exc):
                    raise
                paused = workflow.pause(run_id)
                typer.echo()
                _emit(
                    {
                        "run_id": run_id,
                        "stage": paused.stage.value,
                        "status": paused.status.value,
                    },
                    json_output,
                )
                return

        structured = _structured_from_checkpoint(checkpoint)
        if checkpoint.stage is InitStage.INTERVIEW:
            if answer_payload is not None:
                structured = _build_structured(snapshot, answer_payload)
                confirmed = {"answers": answer_payload}
            else:
                assert conversation_result is not None
                structured = conversation_result
                confirmed = {}
            checkpoint = workflow.advance(
                run_id,
                InitStage.MODEL,
                confirmed=confirmed,
            )
            checkpoint = workflow.advance(
                run_id,
                InitStage.RESOLVE,
                confirmed={"structured_result": structured.model_dump(mode="json")},
            )
            checkpoint = workflow.advance(run_id, InitStage.REVIEW)

        assert structured is not None
        stored_answers = checkpoint.confirmed.get("answers", {})
        fact_answers = (
            answer_payload
            if answer_payload is not None
            else stored_answers
            if isinstance(stored_answers, Mapping)
            else {}
        )
        snapshot = _repository_with_project_type(snapshot, fact_answers)
        requested_remote_decisions = _parse_remote_decisions(remote_decision or [])
        stored_remote_decisions = _load_remote_decisions(root)
        effective_remote_decisions = {
            **stored_remote_decisions,
            **requested_remote_decisions,
        }
        discovery_enabled = remote_discovery or bool(
            structured.blueprint.preferences.get("remote_discovery", False)
        )
        remote_candidates, remote_evidence = (
            _load_remote_snapshot(root) if discovery_enabled else ((), {})
        )
        suppressed_remote_candidates = frozenset(effective_remote_decisions)
        project_plan = build_project_plan(
            root,
            structured.blueprint,
            snapshot,
            inventory=inventory,
            remote_candidates=remote_candidates,
            remote_evidence=remote_evidence,
            rejected_remote_candidates=suppressed_remote_candidates,
        )
        if checkpoint.stage is InitStage.REVIEW and answer_payload is not None:
            structured = _build_structured(snapshot, answer_payload)
            checkpoint = workflow.revise(
                run_id,
                confirmed={"structured_result": structured.model_dump(mode="json")},
            )
            project_plan = build_project_plan(
                root,
                structured.blueprint,
                snapshot,
                inventory=inventory,
                remote_candidates=remote_candidates,
                remote_evidence=remote_evidence,
                rejected_remote_candidates=suppressed_remote_candidates,
            )
        review_payload = _review_payload(run_id, checkpoint, structured)
        review_payload.update(
            _plan_payload(
                project_plan.inventory, project_plan.requirements, project_plan.resolution
            )
        )
        if checkpoint.stage is InitStage.REVIEW and not confirm:
            paused = workflow.pause(run_id)
            review_payload.update(status=paused.status.value, stage=paused.stage.value)
            _emit(review_payload, json_output)
            return
        if checkpoint.stage is not InitStage.REVIEW:
            raise InvalidTransition(
                f"run {run_id!r} cannot continue review from {checkpoint.stage.value}"
            )

        checkpoint = workflow.advance(run_id, InitStage.APPLY)
        if model_only:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(structured.blueprint.model_dump_json(indent=2), encoding="utf-8")
            applied_paths: tuple[str, ...] = ()
            completion_details = {"blueprint_output": str(output_path)}
        else:
            changeset = _project_changeset(
                root,
                structured.blueprint,
                inventory=project_plan.inventory,
                resolution=project_plan.resolution,
                requirements=project_plan.requirements,
                git_init_decision=git_init if snapshot.is_empty else None,
                remote_decisions=effective_remote_decisions,
            )
            preview = render_dry_run(changeset)
            if dry_run:
                applied_paths = ()
                completion_details = {"dry_run_changeset": changeset.digest}
                review_payload.update(status="dry-run", preview=preview, applied_paths=[])
            else:
                result = apply_changeset(changeset)
                applied_paths = result.applied_paths
                completion_details = {"applied_changeset": changeset.digest}
        workflow.advance(run_id, InitStage.VERIFY)
        completed = workflow.complete(run_id, confirmed=completion_details)
        if not dry_run:
            review_payload.update(
                status=completed.status.value,
                stage=completed.stage.value,
                applied_paths=list(applied_paths),
            )
        _emit(review_payload, json_output)
    except (
        OSError,
        CodexStructuredResultError,
        UnicodeError,
        ValueError,
        ApplyFailure,
        ConcurrentChangeError,
        CheckpointConflict,
        InvalidTransition,
    ) as exc:
        typer.echo(f"initialization failed: {exc}", err=True)
        raise typer.Exit(2) from exc


def _contains_user_abort(exc: BaseExceptionGroup) -> bool:
    return any(
        isinstance(item, typer.Abort)
        or (isinstance(item, BaseExceptionGroup) and _contains_user_abort(item))
        for item in exc.exceptions
    )


def _interview_unknowns(snapshot: RepositorySnapshot) -> tuple[str, ...]:
    confirmed = {
        "project.type" if fact.key == "project_type" else fact.key
        for fact in snapshot.facts
        if fact.confidence is FactConfidence.CONFIRMED
    }
    return tuple(question_id for question_id in QUESTION_ORDER if question_id not in confirmed)


def _ask_interview_question(question: InterviewQuestion) -> str:
    return cast(str, typer.prompt(question.text))


def _project_changeset(
    root: Path,
    blueprint: Blueprint,
    *,
    inventory: InventoryResult | None = None,
    resolution: ResolutionPlan | None = None,
    requirements: tuple[AbstractCapabilityRequirement, ...] | None = None,
    git_init_decision: bool | None = None,
    remote_decisions: Mapping[str, str] | None = None,
) -> ChangeSet:
    if inventory is None or resolution is None or requirements is None:
        plan = build_project_plan(root, blueprint, _complete_snapshot(root))
        inventory = plan.inventory
        resolution = plan.resolution
        requirements = plan.requirements
    rendered = render_project_configuration(
        blueprint, resolution, inventory, requirements=requirements
    )
    rendered_files = rendered.as_dict()
    if git_init_decision is not None:
        decision = "approved" if git_init_decision else "declined"
        rendered_files[".ai-project/decisions.md"] += (
            f"\n## Blank-project bootstrap\n\n- Git initialization: {decision}\n"
        )
    if remote_decisions:
        rendered_files[".ai-project/decisions.md"] += (
            "\n## Remote candidate decisions\n\n"
            + "".join(
                f"- {candidate_ref}: {_decision_past_tense(decision)}\n"
                for candidate_ref, decision in sorted(remote_decisions.items())
            )
        )
        rejection_path = root / ".ai-project" / "rejections.json"
        rejection_payload: dict[str, object] = {}
        if rejection_path.is_file():
            existing_payload = json.loads(
                rejection_path.read_text(encoding="utf-8-sig")
            )
            if isinstance(existing_payload, dict):
                rejection_payload.update(existing_payload)
        rejection_payload.update(
            remote_candidates=sorted(remote_decisions),
            remote_decisions=dict(sorted(remote_decisions.items())),
        )
        rejection_payload.setdefault("capabilities", [])
        rendered_files[".ai-project/rejections.json"] = json.dumps(
            rejection_payload,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
    proposals = [
        ChangeProposal(
            path=path,
            desired_content=content,
            ownership=FileOwnership.OWNED,
            source="project-configuration-template-v1",
            reason="materialize approved project AI configuration",
        )
        for path, content in rendered_files.items()
    ]
    proposals.extend(
        ChangeProposal(
            path=path,
            desired_content=None,
            ownership=FileOwnership.OWNED,
            source="project-capability-manager-migration-v1",
            reason="remove obsolete generated project-development Skill file",
        )
        for path in (
            ".agents/skills/project-development/SKILL.md",
            ".agents/skills/project-development/references/capability-routing.md",
            ".agents/skills/project-development/references/quality-gates.md",
        )
    )
    agents_path = root / "AGENTS.md"
    existing_agents = agents_path.read_bytes() if agents_path.is_file() else None
    managed_guidance = render_agents_guidance()
    merged_agents = merge_agents_md(existing_agents, managed_guidance).decode("utf-8")
    proposals.append(
        ChangeProposal(
            path="AGENTS.md",
            desired_content=merged_agents,
            ownership=FileOwnership.MANAGED,
            source="project-capability-manager-skill-v1",
            reason="govern missing, unhealthy, or explicitly managed capabilities",
        )
    )
    commands: tuple[CommandProposal, ...] = ()
    if git_init_decision and not (root / ".git").exists():
        commands = (
            CommandProposal(
                argv=("git", "init"),
                source="blank-project-bootstrap-v1",
                reason="initialize version control with explicit user consent",
            ),
        )
    return build_changeset(root, tuple(proposals), commands=commands)


def _open_run(
    workflow: InitializationGraph,
    *,
    run_id: str,
    repository_digest: str,
    resume: bool,
) -> InitCheckpoint:
    if not resume:
        return workflow.start(run_id, repository_digest=repository_digest)
    checkpoint = workflow.load(run_id)
    if checkpoint.status is InitStatus.PAUSED:
        return workflow.resume(run_id, repository_digest=repository_digest)
    if checkpoint.status is InitStatus.RUNNING and checkpoint.stage is InitStage.INTERVIEW:
        if checkpoint.repository_digest != repository_digest:
            raise InvalidTransition("repository digest changed; direct resume rejected")
        return checkpoint
    raise InvalidTransition(f"run {run_id!r} is {checkpoint.status.value}, not paused")


RemoteDecision = Literal["accept", "reject", "defer"]


def _parse_remote_decisions(values: list[str]) -> dict[str, RemoteDecision]:
    decisions: dict[str, RemoteDecision] = {}
    for value in values:
        candidate_ref, separator, decision = value.rpartition("=")
        if not separator or not candidate_ref or decision not in {"accept", "reject", "defer"}:
            raise ValueError(
                "--remote-decision must use CANDIDATE_REF=accept|reject|defer"
            )
        decisions[candidate_ref] = cast(RemoteDecision, decision)
    return decisions


def _load_remote_decisions(root: Path) -> dict[str, RemoteDecision]:
    path = root / ".ai-project" / "rejections.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    values = payload.get("remote_decisions", {})
    if not isinstance(values, dict):
        raise ValueError(".ai-project/rejections.json remote_decisions must be an object")
    return _parse_remote_decisions([f"{key}={value}" for key, value in values.items()])


def _load_remote_snapshot(
    root: Path,
) -> tuple[tuple[RemoteCandidate, ...], dict[str, CandidateEvidence]]:
    path = root / ".ai-project" / "remote-candidates.json"
    if not path.is_file():
        return (), {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    candidates_raw = payload.get("candidates", [])
    evidence_raw = payload.get("evidence", {})
    if not isinstance(candidates_raw, list) or not isinstance(evidence_raw, dict):
        raise ValueError("remote candidate snapshot must contain candidates and evidence")
    candidates = tuple(RemoteCandidate.model_validate(item) for item in candidates_raw)
    evidence = {
        candidate_ref: CandidateEvidence(
            platforms=tuple(item.get("platforms", ())),
            project_fact_matches=tuple(item.get("project_fact_matches", ())),
            maintenance=int(item.get("maintenance", 0)),
            adoption=int(item.get("adoption", 0)),
            scan_flags=tuple(item.get("scan_flags", ())),
        )
        for candidate_ref, item in evidence_raw.items()
        if isinstance(candidate_ref, str) and isinstance(item, dict)
    }
    return candidates, evidence


def _decision_past_tense(decision: str) -> str:
    return {"accept": "accepted", "reject": "rejected", "defer": "deferred"}[decision]


def _load_answers(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("answers must be a JSON object")
    return cast(dict[str, Any], raw)


def _repository_with_project_type(
    snapshot: RepositorySnapshot, answers: Mapping[str, Any]
) -> RepositorySnapshot:
    answer = answers.get("project_type", answers.get("project.type"))
    if not isinstance(answer, str) or not answer.strip():
        return snapshot
    confirmed = RepositoryFact(
        key="project_type",
        value=answer.strip(),
        confidence=FactConfidence.CONFIRMED,
        sources=("interview:project.type",),
    )
    facts = tuple(fact for fact in snapshot.facts if fact.key != "project_type")
    return snapshot.model_copy(update={"facts": (*facts, confirmed)})


def _build_structured(
    snapshot: RepositorySnapshot, answers: dict[str, Any]
) -> StructuredProjectResult:
    required = ("goal", "lifecycle_stage", "risk_level")
    missing = [key for key in required if key not in answers]
    if missing:
        raise ValueError(f"answers are missing required fields: {', '.join(missing)}")
    blueprint_payload = {
        "project_name": answers.get("project_name", snapshot.root.name),
        "goal": answers["goal"],
        "lifecycle_stage": answers["lifecycle_stage"],
        "risk_level": answers["risk_level"],
        "target_platforms": answers.get("target_platforms", ("codex",)),
        "constraints": answers.get("constraints", ()),
        "preferences": answers.get("preferences", {}),
        "repository_digest": snapshot.source_digest,
    }
    blueprint = Blueprint.model_validate(blueprint_payload)
    confirmed_fields = set(answers) & set(Blueprint.model_fields)
    field_sources = {
        field: (ValueSource.CONFIRMED if field in confirmed_fields else ValueSource.INFERRED)
        for field in blueprint_payload
    }
    return StructuredProjectResult(
        blueprint=blueprint,
        field_sources=field_sources,
        locked_decisions=frozenset(confirmed_fields),
    )


def _structured_from_checkpoint(
    checkpoint: InitCheckpoint,
) -> StructuredProjectResult | None:
    raw = checkpoint.confirmed.get("structured_result")
    if raw is None:
        return None
    return StructuredProjectResult.model_validate(raw)


def _review_payload(
    run_id: str,
    checkpoint: InitCheckpoint,
    structured: StructuredProjectResult,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "status": checkpoint.status.value,
        "stage": checkpoint.stage.value,
        "blueprint": structured.blueprint.model_dump(mode="json"),
        "field_sources": {
            key: value.value for key, value in sorted(structured.field_sources.items())
        },
        "locked_decisions": sorted(structured.locked_decisions),
    }


def _plan_payload(
    inventory: InventoryResult,
    requirements: tuple[AbstractCapabilityRequirement, ...],
    resolution: ResolutionPlan,
) -> dict[str, object]:
    return {
        "inventory": {
            "capability_ids": [item.manifest.capability_id for item in inventory.capabilities],
            "diagnostics": [
                {
                    "adapter_id": item.adapter_id,
                    "code": item.code,
                    "message": item.message,
                    "capability_id": item.capability_id,
                    "locator": item.locator,
                    "adapter_ids": list(item.adapter_ids),
                }
                for item in inventory.diagnostics
            ],
            "digest": inventory.inventory_digest,
        },
        "resolution": resolution.model_dump(mode="json"),
        "requirements": [
            item.model_dump(mode="json")
            for item in sorted(requirements, key=lambda value: value.capability)
        ],
        "decisions": [
            item.model_dump(mode="json")
            for item in sorted(
                resolution.resolutions,
                key=lambda value: (
                    value.requirement,
                    value.status.value,
                    value.capability_id or "",
                ),
            )
        ],
    }


def _emit(payload: Mapping[str, object], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return
    for key, value in payload.items():
        typer.echo(f"{key}: {value}")
