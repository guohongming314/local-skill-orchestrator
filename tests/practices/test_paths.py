from __future__ import annotations

from vibe.practices.paths import bundled_practice_packs_root


def test_bundled_practice_packs_are_available_to_runtime() -> None:
    root = bundled_practice_packs_root()

    assert root.is_dir()
    assert (root / "base-engineering/pack.yaml").is_file()
    assert (root / "web-application/pack.yaml").is_file()
