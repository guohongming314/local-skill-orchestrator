from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def read() -> dict[str, Any]:
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    value = json.loads(line)
    if not isinstance(value, dict):
        raise TypeError("expected object")
    return value


def emit(value: object) -> None:
    print(json.dumps(value, separators=(",", ":")), flush=True)


def main() -> None:
    mode = sys.argv[1]
    state_path = Path(sys.argv[2])
    request = read()
    emit(
        {
            "id": request["id"],
            "result": {
                "userAgent": "fake-codex/1.0",
                "codexHome": str(state_path.parent),
                "platformFamily": "unix",
                "platformOs": "linux",
            },
        }
    )
    if read().get("method") != "initialized":
        raise ValueError("initialized required")

    prompts: list[str] = []
    approval_responses: list[dict[str, Any]] = []
    context: dict[str, Any] = {}
    turn_count = 0
    while True:
        try:
            request = read()
        except EOFError:
            break
        method = request.get("method")
        if method == "thread/resume":
            if mode == "lost-thread":
                emit(
                    {"id": request["id"], "error": {"code": -32001, "message": "thread not found"}}
                )
            else:
                emit(
                    {
                        "id": request["id"],
                        "result": {"thread": {"id": request["params"]["threadId"]}},
                    }
                )
            continue
        if method == "thread/start":
            emit({"id": request["id"], "result": {"thread": {"id": "interview-1"}}})
            continue
        if method != "turn/start":
            if "id" in request and "method" not in request:
                approval_responses.append(request)
                continue
            raise ValueError(f"unexpected method {method}")

        turn_count += 1
        params = request["params"]
        thread_id = params["threadId"]
        text = params["input"][0]["text"]
        prompts.append(text)
        if turn_count == 1:
            context = json.loads(text)

        turn_id = f"turn-{turn_count}"
        turn: dict[str, Any] = {
            "id": turn_id,
            "status": "inProgress",
            "items": [],
            "error": None,
        }
        emit({"id": request["id"], "result": {"turn": turn}})
        emit({"method": "turn/started", "params": {"threadId": thread_id, "turn": turn}})
        if turn_count == 1:
            emit(
                {
                    "id": "approval-1",
                    "method": "item/commandExecution/requestApproval",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "itemId": "command-1",
                    },
                }
            )

        if "outputSchema" in params:
            if mode == "invalid":
                text_out = "not json"
            else:
                repository = context["repository"]
                text_out = json.dumps(
                    {
                        "blueprint": {
                            "project_name": Path(repository["root"]).name,
                            "goal": "Ship a safe service",
                            "lifecycle_stage": "active-development",
                            "risk_level": "medium",
                            "constraints": [{"name": "compliance", "value": "SOC 2"}],
                            "preferences": {"testing": "test-first"},
                            "repository_digest": repository["source_digest"],
                        },
                        "field_sources": {
                            "project_name": "inferred",
                            "goal": "confirmed",
                            "lifecycle_stage": "confirmed",
                            "risk_level": "confirmed",
                            "constraints": "confirmed",
                            "preferences": "confirmed",
                            "repository_digest": "inferred",
                        },
                    }
                )
        else:
            text_out = "acknowledged"
        item = {"id": f"item-{turn_count}", "type": "agentMessage", "text": text_out}
        emit(
            {
                "method": "item/completed",
                "params": {"threadId": thread_id, "turnId": turn_id, "item": item},
            }
        )
        emit(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {**turn, "status": "completed", "items": [item]},
                },
            }
        )
        state_path.write_text(
            json.dumps(
                {
                    "prompts": prompts,
                    "approval_responses": approval_responses,
                    "turn_count": turn_count,
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
