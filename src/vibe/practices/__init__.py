"""Versioned, data-only engineering practice packs."""

from __future__ import annotations

from typing import Any

__all__ = ["PracticePack", "load_practice_pack", "load_practice_packs"]


def __getattr__(name: str) -> Any:
    if name == "PracticePack":
        from vibe.practices.models import PracticePack

        return PracticePack
    if name in {"load_practice_pack", "load_practice_packs"}:
        from vibe.practices.loader import load_practice_pack, load_practice_packs

        return {
            "load_practice_pack": load_practice_pack,
            "load_practice_packs": load_practice_packs,
        }[name]
    raise AttributeError(name)
