from __future__ import annotations

from collections.abc import Iterator

import pytest

from vibe.migrations.registry import default_registry


@pytest.fixture(autouse=True)
def isolate_default_registry() -> Iterator[None]:
    default_registry.clear()
    yield
    default_registry.clear()
