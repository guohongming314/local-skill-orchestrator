from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    mode = sys.argv[1]
    invocation_path = Path(sys.argv[2])
    argv = sys.argv[3:]
    schema_path = Path(argv[argv.index("--output-schema") + 1])
    output_path = Path(argv[argv.index("--output-last-message") + 1])
    cwd = Path(argv[argv.index("--cd") + 1])
    invocation_path.write_text(
        json.dumps({"argv": argv, "schema": json.loads(schema_path.read_text()), "cwd": str(cwd)})
    )
    if mode == "crash":
        print("x" * 5000, file=sys.stderr)
        raise SystemExit(23)
    output = (
        {"summary": "fallback", "turn_count": 2}
        if mode == "valid"
        else {"summary": "", "turn_count": 0}
    )
    output_path.write_text(json.dumps(output))


if __name__ == "__main__":
    main()
