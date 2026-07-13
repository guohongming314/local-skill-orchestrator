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
                "platformFamily": "windows",
                "platformOs": "windows",
            },
        }
    )
    initialized = read()
    if initialized.get("method") != "initialized":
        raise ValueError("initialized required")
    turn_count = 0
    thread_ids: list[str] = []
    while True:
        try:
            request = read()
        except EOFError:
            return
        method = request["method"]
        if method == "thread/start":
            emit({"id": request["id"], "result": {"thread": {"id": "thread-1"}}})
            continue
        if method != "turn/start":
            raise ValueError(f"unexpected method {method}")
        turn_count += 1
        thread_id = request["params"]["threadId"]
        thread_ids.append(thread_id)
        state_path.write_text(
            json.dumps({"turn_count": turn_count, "thread_ids": thread_ids})
        )
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
            text = "context established"
        elif mode == "structured-valid":
            text = json.dumps({"summary": "validated", "turn_count": 2})
        elif mode == "structured-repair" and turn_count >= 3:
            text = json.dumps({"summary": "repaired", "turn_count": 3})
        else:
            text = "not json"
        item = {"id": f"item-{turn_count}", "type": "agentMessage", "text": text}
        emit(
            {
                "method": "item/started",
                "params": {"threadId": thread_id, "turnId": turn_id, "item": item},
            }
        )
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


if __name__ == "__main__":
    main()
