"""Structured Codex result validation and isolated ``codex exec`` fallback."""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

import anyio
from pydantic import BaseModel, ValidationError

_MAX_STDERR = 800


class StructuredResultError(RuntimeError):
    """A structured result could not be produced or validated."""


def validate_structured_result[ResultT: BaseModel](
    raw: str,
    model_type: type[ResultT],
    *,
    source: str,
) -> ResultT:
    """Decode and validate one JSON model result with an actionable source label."""
    try:
        return model_type.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise StructuredResultError(f"{source} is not valid {model_type.__name__} JSON") from exc


class CodexExecFallback:
    """Run a schema-constrained, ephemeral Codex exec process as a last resort."""

    def __init__(self, command: Sequence[str] = ("codex", "exec")) -> None:
        if not command:
            raise ValueError("command must not be empty")
        self._command = tuple(command)

    async def run[ResultT: BaseModel](
        self,
        *,
        prompt: str,
        model_type: type[ResultT],
        cwd: Path,
    ) -> ResultT:
        with tempfile.TemporaryDirectory(prefix="vibe-codex-exec-") as temporary:
            directory = Path(temporary)
            schema_path = directory / "schema.json"
            output_path = directory / "result.json"
            schema_path.write_text(json.dumps(model_type.model_json_schema()), encoding="utf-8")
            command = (
                *self._command,
                "--json",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--cd",
                str(cwd.resolve()),
                "--ephemeral",
                prompt,
            )
            completed = await anyio.run_process(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            stderr = completed.stderr.decode("utf-8", errors="replace")[:_MAX_STDERR]
            if completed.returncode != 0:
                detail = f": {stderr}" if stderr else ""
                raise StructuredResultError(
                    f"codex exec fallback exited with exit code {completed.returncode}{detail}"
                )
            if not output_path.is_file():
                raise StructuredResultError("codex exec fallback did not write its final message")
            return validate_structured_result(
                output_path.read_text(encoding="utf-8"),
                model_type,
                source="fallback output",
            )
