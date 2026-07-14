from __future__ import annotations

from pathlib import Path
from typing import Any

from vibe.doctor.checks import DoctorContext, SchemaVersionCheck
from vibe.inventory.service import InventoryResult
from vibe.migrations.registry import ArtifactKind, default_registry


def bump(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "schema_version": "2"}


def test_doctor_reports_artifacts_on_old_schema_versions(tmp_path: Path) -> None:
    default_registry.clear()
    default_registry.register(ArtifactKind.GENERATED_CONFIG, "1", "2", bump)
    target = tmp_path / ".ai-project" / "policy.yaml"
    target.parent.mkdir()
    target.write_text("schema_version: '1'\n", encoding="utf-8")
    context = DoctorContext(
        root=tmp_path,
        inventory=InventoryResult(capabilities=(), diagnostics=(), inventory_digest="empty"),
        command_resolver=lambda command: command,
    )

    findings = SchemaVersionCheck().check(context)

    assert len(findings) == 1
    assert findings[0].code == "configuration.schema-outdated"
    assert findings[0].evidence == (".ai-project/policy.yaml", "1 -> 2")
    assert "vibe migrate" in findings[0].remediation
