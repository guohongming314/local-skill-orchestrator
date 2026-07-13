"""Typed Doctor findings and deterministic report aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class DoctorFinding:
    code: str
    severity: Severity
    summary: str
    evidence: tuple[str, ...]
    remediation: str


@dataclass(frozen=True)
class DoctorReport:
    findings: tuple[DoctorFinding, ...]

    @property
    def healthy(self) -> bool:
        return not any(item.severity is Severity.ERROR for item in self.findings)


def aggregate_findings(findings: tuple[DoctorFinding, ...]) -> DoctorReport:
    return DoctorReport(
        tuple(sorted(findings, key=lambda item: (item.code, item.evidence, item.summary)))
    )
