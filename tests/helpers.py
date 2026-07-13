from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class CommandRunner:
    cwd: Path
    environment: Mapping[str, str]

    def run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=self.cwd,
            env=dict(self.environment),
            check=False,
            capture_output=True,
            text=True,
        )

    def run_python(self, code: str) -> subprocess.CompletedProcess[str]:
        return self.run((sys.executable, "-c", code))


@dataclass(frozen=True)
class FrozenClock:
    current: datetime

    def now(self) -> datetime:
        return self.current
