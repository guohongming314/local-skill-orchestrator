"""Model-only project initialization command."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from vibe.commands.inspect import _complete_snapshot
from vibe.conversation.interview import InterviewInput, build_interview
from vibe.conversation.structured_result import StructuredProjectResult, ValueSource
from vibe.models.blueprint import Blueprint
from vibe.models.repository import RepositorySnapshot
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
) -> None:
    """Inspect, interview, and review a Blueprint without materializing a project."""
    if not model_only:
        typer.echo("only --model-only initialization is available", err=True)
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
            cancelled = workflow.cancel(run_id, reason="user cancelled model-only review")
            _emit({"run_id": run_id, "status": cancelled.status.value}, json_output)
            return

        if checkpoint.stage is InitStage.INSPECT:
            checkpoint = workflow.advance(
                run_id,
                InitStage.INVENTORY,
                confirmed={"repository": snapshot.model_dump(mode="json")},
            )
        if checkpoint.stage is InitStage.INVENTORY:
            checkpoint = workflow.advance(
                run_id,
                InitStage.INTERVIEW,
                confirmed={"inventory_summary": []},
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
        if checkpoint.stage is InitStage.REVIEW and answer_payload is not None:
            structured = _build_structured(snapshot, answer_payload)
            checkpoint = workflow.revise(
                run_id,
                confirmed={"structured_result": structured.model_dump(mode="json")},
            )
        review_payload = _review_payload(run_id, checkpoint, structured)
        if checkpoint.stage is InitStage.REVIEW and not confirm:
            paused = workflow.pause(run_id)
            review_payload.update(status=paused.status.value, stage=paused.stage.value)
            _emit(review_payload, json_output)
            return
        if checkpoint.stage is not InitStage.REVIEW:
            raise InvalidTransition(
                f"run {run_id!r} cannot continue model-only review from {checkpoint.stage.value}"
            )

        checkpoint = workflow.advance(run_id, InitStage.APPLY)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(structured.blueprint.model_dump_json(indent=2), encoding="utf-8")
        workflow.advance(run_id, InitStage.VERIFY)
        completed = workflow.complete(
            run_id,
            confirmed={"blueprint_output": str(output_path)},
        )
        review_payload.update(status=completed.status.value, stage=completed.stage.value)
        _emit(review_payload, json_output)
    except (OSError, ValueError, CheckpointConflict, InvalidTransition) as exc:
        typer.echo(f"initialization failed: {exc}", err=True)
        raise typer.Exit(2) from exc


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


def _emit(payload: Mapping[str, object], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return
    for key, value in payload.items():
        typer.echo(f"{key}: {value}")
