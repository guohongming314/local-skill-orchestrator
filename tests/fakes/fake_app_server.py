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


def main() -> None:
    scenario = sys.argv[1]

    if scenario == "concurrent":
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
