from __future__ import annotations

import yaml

from vibe.materialize.codex_metadata import render_capability_manager_metadata


def test_capability_manager_metadata_is_deterministic_and_codex_native() -> None:
    first = render_capability_manager_metadata()
    second = render_capability_manager_metadata()

    assert first == second
    assert yaml.safe_load(first) == {
        "interface": {
            "display_name": "Project Capability Manager",
            "short_description": "Govern missing or unhealthy project capabilities",
            "default_prompt": (
                "Use $project-capability-manager to diagnose and manage a missing "
                "or unhealthy project capability."
            ),
        },
        "policy": {"allow_implicit_invocation": True},
    }
