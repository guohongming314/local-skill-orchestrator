"""Deterministic Codex metadata for generated project Skills."""

from __future__ import annotations

import yaml


def render_capability_manager_metadata() -> str:
    """Render the supported Codex metadata for the capability manager."""
    return yaml.safe_dump(
        {
            "interface": {
                "display_name": "Project Capability Manager",
                "short_description": "Govern missing or unhealthy project capabilities",
                "default_prompt": (
                    "Use $project-capability-manager to diagnose and manage a missing "
                    "or unhealthy project capability."
                ),
            },
            "policy": {"allow_implicit_invocation": True},
        },
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )

