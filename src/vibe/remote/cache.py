"""Small filesystem response cache for remote discovery metadata."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vibe.remote.models import CacheStatus


@dataclass(frozen=True)
class CachedResponse:
    payload: Mapping[str, Any]
    status: CacheStatus


class ResponseCache:
    """Cache JSON responses below the configured vibe home."""

    def __init__(
        self,
        vibe_home: Path,
        *,
        ttl_seconds: float,
        max_snapshot_age_seconds: float | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = vibe_home / "cache" / "remote"
        self._ttl = ttl_seconds
        self._max_age = max_snapshot_age_seconds or ttl_seconds * 4
        self._clock = clock

    def get(self, namespace: str, key: str) -> CachedResponse | None:
        path = self._path(namespace, key)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            stored_at = float(document["stored_at"])
            payload = document["payload"]
            if not isinstance(payload, dict):
                return None
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None
        age = max(0.0, self._clock() - stored_at)
        if age <= self._ttl:
            status = CacheStatus.FRESH
        elif age <= self._max_age:
            status = CacheStatus.STALE
        else:
            status = CacheStatus.EXPIRED
        return CachedResponse(payload=payload, status=status)

    def put(self, namespace: str, key: str, payload: Mapping[str, Any]) -> None:
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"payload": payload, "stored_at": self._clock()}
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"))
        temporary = path.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(path)

    def _path(self, namespace: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self._root / namespace / f"{digest}.json"
