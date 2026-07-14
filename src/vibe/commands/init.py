"""Model-only project initialization command."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from vibe.commands.inspect import _complete_snapshot
from vibe.commands.project_plan import build_project_plan, scan_project_inventory
from vibe.conversation.interview import InterviewInput, build_interview
from vibe.conversation.structured_result import StructuredProjectResult, ValueSource
from vibe.inventory.service import InventoryResult
from vibe.materialize.agents_md import merge_agents_md
from vibe.materialize.changeset import (
    ChangeProposal,
    ChangeSet,
    build_changeset,
    render_dry_run,
)
from vibe.materialize.ownership import FileOwnership
from vibe.materialize.templates import render_project_configuration
from vibe.materialize.writer import ApplyFailure, ConcurrentChangeError, apply_changeset
from vibe.models.blueprint import Blueprint
from vibe.models.repository import FactConfidence, RepositoryFact, RepositorySnapshot
from vibe.models.resolution import ResolutionPlan
from vibe.resolver.requirements import AbstractCapabilityRequirement
from vibe.workflows.checkpoints import CheckpointConflict, SqliteCheckpointStore
from vibe.workflows.init_graph import InitializationGraph, InvalidTransition
from vibe.workflows.state import InitCheckpoint, InitStage, InitStatus


def init_command(
    model_only: Annotated[bool, typer.Option("--model-only")] = False,
    path: Annotated[
        Path | None,
        typer.Option("--path", exists=True, file_okay=False, resolve_path=True),
    ] = None,
    run_id: Annotated[str, typer.Option("--run-id")] = "init",
    checkpoints: Annotated[Path | None, typer.Option("--checkpoints")] = None,
    answers: Annotated[
        Path | None, typer.Option("--answers", exists=True, dir_okay=False)
    ] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    resume: Annotated[bool, typer.Option("--resume")] = False,
    confirm: Annotated[bool, typer.Option("--confirm")] = False,
    cancel: Annotated[bool, typer.Option("--cancel")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Inspect, review, and optionally materialize project AI configuration."""
    if model_only and dry_run:
        typer.echo("--dry-run cannot be combined with --model-only", err=True)
        raise typer.Exit(2)
    root = (path or Path.cwd()).resolve()
    checkpoint_path = (checkpoints or root / ".vibe-init-checkpoints.sqlite3").resolve()
    output_path = (output or root / "blueprint.json").resolve()
    workflow = InitializationGraph(SqliteCheckpointStore(checkpoint_path))

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
        if checkpoint.stage is InitStage.INTERVIEW and answer_payload is None:
            interview = build_interview(
                InterviewInput(
                    repository=snapshot,
                    unknowns=("project.goal", "project.lifecycle", "risk.tolerance"),
                )
            )
            paused = workflow.pause(run_id)
            _emit(
                {
                    "run_id": run_id,
                    "status": paused.status.value,
                    "stage": paused.stage.value,
                    "questions": [
                        {
                            "id": question.question_id,
                            "text": question.text,
                            "requires_explicit_confirmation": (
                                question.requires_explicit_confirmation
                            ),
                        }
                        for question in interview.questions
                    ],
                },
                json_output,
            )
            return

        structured = _structured_from_checkpoint(checkpoint)
        if checkpoint.stage is InitStage.INTERVIEW:
            assert answer_payload is not None
            structured = _build_structured(snapshot, answer_payload)
            checkpoint = workflow.advance(
                run_id,
                InitStage.MODEL,
                confirmed={"answers": answer_payload},
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
            else stored_answers if isinstance(stored_answers, Mapping) else {}
        )
        snapshot = _repository_with_project_type(snapshot, fact_answers)
        project_plan = build_project_plan(
            root, structured.blueprint, snapshot, inventory=inventory
        )
        if checkpoint.stage is InitStage.REVIEW and answer_payload is not None:
            structured = _build_structured(snapshot, answer_payload)
            checkpoint = workflow.revise(
                run_id,
                confirmed={"structured_result": structured.model_dump(mode="json")},
            )
            project_plan = build_project_plan(
                root, structured.blueprint, snapshot, inventory=inventory
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
            output_path.write_text(
                structured.blueprint.model_dump_json(indent=2), encoding="utf-8"
            )
            applied_paths: tuple[str, ...] = ()
            completion_details = {"blueprint_output": str(output_path)}
        else:
            changeset = _project_changeset(
                root,
                structured.blueprint,
                inventory=project_plan.inventory,
                resolution=project_plan.resolution,
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
        UnicodeError,
        ValueError,
        ApplyFailure,
        ConcurrentChangeError,
        CheckpointConflict,
        InvalidTransition,
    ) as exc:
        typer.echo(f"initialization failed: {exc}", err=True)
        raise typer.Exit(2) from exc


def _project_changeset(
    root: Path,
    blueprint: Blueprint,
    *,
    inventory: InventoryResult | None = None,
    resolution: ResolutionPlan | None = None,
) -> ChangeSet:
    if inventory is None or resolution is None:
        plan = build_project_plan(root, blueprint, _complete_snapshot(root))
        inventory = plan.inventory
        resolution = plan.resolution
    rendered = render_project_configuration(blueprint, resolution, inventory)
    proposals = [
        ChangeProposal(
            path=path,
            desired_content=content,
            ownership=FileOwnership.OWNED,
            source="project-configuration-template-v1",
            reason="materialize approved project AI configuration",
        )
        for path, content in rendered.as_dict().items()
    ]
    agents_path = root / "AGENTS.md"
    existing_agents = agents_path.read_bytes() if agents_path.is_file() else None
    managed_guidance = (
        "## Project development\n\n"
        "Use the project-development Skill at "
        "`.agents/skills/project-development/SKILL.md`.\n"
    )
    merged_agents = merge_agents_md(existing_agents, managed_guidance).decode("utf-8")
    proposals.append(
        ChangeProposal(
            path="AGENTS.md",
            desired_content=merged_agents,
            ownership=FileOwnership.MANAGED,
            source="project-development-skill-v1",
            reason="route project work through generated local guidance",
        )
    )
    return build_changeset(root, tuple(proposals))


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
    raise InvalidTransition(
        f"run {run_id!r} is {checkpoint.status.value}, not paused"
    )


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
        field: (
            ValueSource.CONFIRMED if field in confirmed_fields else ValueSource.INFERRED
        )
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
            "capability_ids": [
                item.manifest.capability_id for item in inventory.capabilities
            ],
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
                    value.requirement, value.status.value, value.capability_id or ""
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
