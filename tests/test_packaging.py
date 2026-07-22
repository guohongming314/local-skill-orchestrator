from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


def test_wheel_contains_runtime_practice_packs(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("*.whl"))

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    assert "vibe/practices/packs/base-engineering/pack.yaml" in names
    assert "vibe/practices/packs/web-application/pack.yaml" in names
