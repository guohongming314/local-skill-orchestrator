"""Versioned local mapping from known provider IDs to abstract capabilities."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

_TAXONOMY_RESOURCE = "data/provider-taxonomy.v1.json"


def provider_capabilities(provider_id: str) -> tuple[str, ...]:
    """Return abstract capabilities for a known provider, or no capabilities."""
    providers = _providers()
    return providers.get(_normalize(provider_id), ())


@lru_cache(maxsize=1)
def _providers() -> dict[str, tuple[str, ...]]:
    payload: Any = json.loads(
        files("vibe.inventory").joinpath(_TAXONOMY_RESOURCE).read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("unsupported provider taxonomy version")
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, dict):
        raise ValueError("provider taxonomy must define providers")

    providers: dict[str, tuple[str, ...]] = {}
    for provider_id, capabilities in raw_providers.items():
        if not isinstance(provider_id, str) or not isinstance(capabilities, list):
            raise ValueError("invalid provider taxonomy entry")
        if not all(isinstance(capability, str) for capability in capabilities):
            raise ValueError("provider capabilities must be strings")
        providers[_normalize(provider_id)] = tuple(sorted(capabilities))
    return providers


def _normalize(provider_id: str) -> str:
    return provider_id.strip().lower().replace("_", "-")
