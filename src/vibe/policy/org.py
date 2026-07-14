"""File-distributed team and organization policy catalog."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import Field

from vibe.models.base import VersionedModel
from vibe.models.capability import Permission
from vibe.remote.models import PermissionLevel

ORG_POLICY_ENV = "VIBE_ORG_POLICY_PATH"


class OrgPolicy(VersionedModel):
    """Organization guardrails loaded from an ``org-policy.yaml`` file."""

    approved_capability_ids: frozenset[str] = Field(default_factory=frozenset)
    blocked_capability_ids: frozenset[str] = Field(default_factory=frozenset)
    approved_publishers: frozenset[str] = Field(default_factory=frozenset)
    blocked_publishers: frozenset[str] = Field(default_factory=frozenset)
    allowed_permissions: frozenset[Permission] = Field(
        default_factory=lambda: frozenset(Permission)
    )
    max_permission_level: PermissionLevel = PermissionLevel.L4
    mandatory_practice_packs: frozenset[str] = Field(default_factory=frozenset)


def org_policy_path(
    root: Path,
    configured_path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve explicit, environment, repository, then user-home policy paths."""
    if configured_path is not None:
        return configured_path.expanduser().resolve()
    environment = os.environ if environ is None else environ
    if configured := environment.get(ORG_POLICY_ENV):
        return Path(configured).expanduser().resolve()
    repository_policy = (root / "org-policy.yaml").resolve()
    if repository_policy.is_file():
        return repository_policy
    return ((home or Path.home()) / ".config" / "vibe" / "org-policy.yaml").resolve()


def load_org_policy(
    root: Path,
    configured_path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> tuple[OrgPolicy | None, Path]:
    """Load the selected policy; a missing file deliberately means no policy."""
    path = org_policy_path(root, configured_path, environ=environ, home=home)
    if not path.is_file():
        return None, path
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"organization policy must be a mapping: {path}")
    return OrgPolicy.model_validate(payload), path
