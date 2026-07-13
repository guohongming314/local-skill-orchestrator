from __future__ import annotations

import json
import sys
import time
from typing import Any


def emit(message: object) -> None:
    print(json.dumps(message, separators=(",", ":")), flush=True)


def read() -> dict[str, Any]:
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    value = json.loads(line)
    if not isinstance(value, dict):
        raise TypeError("expected object")
    return value



def lifecycle(mode: str, state_path: str) -> None:
    from pathlib import Path

    path = Path(state_path)
    initialized = read()
    if initialized.get("method") != "initialize":
        raise ValueError("initialize must be first")
    emit(
        {
            "id": initialized["id"],
            "result": {
                "userAgent": "fake-codex/1.0",
                "codexHome": str(path.parent.resolve()),
                "platformFamily": "windows",
                "platformOs": "windows",
            },
        }
    )
    acknowledgement = read()
    if acknowledgement.get("method") != "initialized" or "id" in acknowledgement:
        raise ValueError("initialized notification required")

    turn_number = 0
    while True:
        try:
            request = read()
        except EOFError:
            return
        method = request.get("method")
        if method == "thread/start":
            thread_id = "thread-persisted"
            path.write_text(json.dumps({"threadId": thread_id}))
            emit({"id": request["id"], "result": {"thread": {"id": thread_id}}})
            emit({"method": "thread/started", "params": {"thread": {"id": thread_id}}})
        elif method == "thread/resume":
            stored = json.loads(path.read_text())
            thread_id = request["params"]["threadId"]
            if thread_id != stored["threadId"]:
                emit(
                    {
                        "id": request["id"],
                        "error": {"code": -32000, "message": "unknown thread"},
                    }
                )
                continue
            emit({"id": request["id"], "result": {"thread": {"id": thread_id}}})
        elif method == "turn/start":
            turn_number += 1
            thread_id = request["params"]["threadId"]
            turn_id = f"turn-{turn_number}"
            turn: dict[str, Any] = {
                "id": turn_id,
                "status": "inProgress",
                "items": [],
                "error": None,
            }
            emit({"id": request["id"], "result": {"turn": turn}})
            emit(
                {
                    "method": "turn/started",
                    "params": {"threadId": thread_id, "turn": turn},
                }
            )
            if mode == "lifecycle":
                text = request["params"]["input"][0]["text"]
                item = {
                    "id": f"item-{turn_number}",
                    "type": "agentMessage",
                    "text": text,
                }
                emit(
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": item,
                        },
                    }
                )
                emit(
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "item": item,
                        },
                    }
                )
                completed = {**turn, "status": "completed", "items": [item]}
                emit(
                    {
                        "method": "turn/completed",
                        "params": {"threadId": thread_id, "turn": completed},
                    }
                )
        elif method == "turn/interrupt":
            params = request["params"]
            path.write_text(params["turnId"])
            emit({"id": request["id"], "result": {}})
            emit(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": params["threadId"],
                        "turn": {
                            "id": params["turnId"],
                            "status": "interrupted",
                            "items": [],
                            "error": None,
                        },
                    },
                }
            )
        else:
            raise ValueError(f"unexpected lifecycle method: {method}")


def main() -> None:
    scenario = sys.argv[1]

    if scenario in {"lifecycle", "interrupt"}:
        lifecycle(scenario, sys.argv[2])
    elif scenario == "concurrent":
        first = read()
        second = read()
        emit({"id": second["id"], "result": {"echo": second["params"]["value"]}})
        emit({"id": first["id"], "result": {"echo": first["params"]["value"]}})
    elif scenario == "routes":
        request = read()
        emit({"method": "turn/started", "params": {"turnId": "turn-1"}})
        emit(
            {
                "id": 9001,
                "method": "item/commandExecution/requestApproval",
                "params": {"reason": "test"},
            }
        )
        response = read()
        emit({"id": request["id"], "result": {"serverResponse": response}})
    elif scenario == "malformed":
        read()
        print("{not json", flush=True)
    elif scenario == "eof":
        read()
    elif scenario == "crash":
        read()
        print("fatal fake app-server failure", file=sys.stderr, flush=True)
        raise SystemExit(23)
    elif scenario == "timeout":
        read()
        time.sleep(30)
    elif scenario == "idle":
        for _line in sys.stdin:
            pass
    elif scenario == "remote-error":
        request = read()
        emit(
            {
                "id": request["id"],
                "error": {
                    "code": -32602,
                    "message": "bad params",
                    "data": {"field": "cwd"},
                },
            }
        )
    else:
        raise ValueError(f"unknown scenario: {scenario}")


if __name__ == "__main__":
    main()
