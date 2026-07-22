"""Resolve Practice Pack data in source checkouts and installed wheels."""

from __future__ import annotations

from pathlib import Path


def bundled_practice_packs_root() -> Path:
    """Return the packaged Practice Pack root with a source-tree fallback."""
    packaged = Path(__file__).resolve().parent / "packs"
    if packaged.is_dir():
        return packaged
    source = Path(__file__).resolve().parents[3] / "practice-packs"
    if source.is_dir():
        return source
    raise FileNotFoundError("bundled Practice Packs are missing")
