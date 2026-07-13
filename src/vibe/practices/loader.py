from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from vibe.practices.models import PracticePack


def load_practice_pack(path: Path) -> PracticePack:
    """Load and strictly validate one versioned YAML Practice Pack."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Practice Pack must be a YAML mapping: {path}")
    return PracticePack.migrate(_string_keyed(payload, path))


def load_practice_packs(root: Path) -> tuple[PracticePack, ...]:
    """Load packs deterministically, independent of filesystem enumeration order."""
    packs = tuple(load_practice_pack(path) for path in root.glob("*/pack.yaml"))
    by_id: dict[str, PracticePack] = {}
    for pack in packs:
        if pack.pack_id in by_id:
            raise ValueError(f"duplicate Practice Pack id: {pack.pack_id}")
        by_id[pack.pack_id] = pack
    return tuple(by_id[pack_id] for pack_id in sorted(by_id))


def _string_keyed(payload: dict[Any, Any], path: Path) -> dict[str, Any]:
    if not all(isinstance(key, str) for key in payload):
        raise ValueError(f"Practice Pack keys must be strings: {path}")
    return {key: value for key, value in payload.items() if isinstance(key, str)}
