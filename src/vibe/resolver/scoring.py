from __future__ import annotations

from dataclasses import dataclass

from vibe.inventory.adapters.base import AdapterScanResult
from vibe.models.capability import CapabilityKind, Permission

_PERMISSION_COST = {
    Permission.READ_PROJECT: 1,
    Permission.EXECUTE_COMMAND: 3,
    Permission.WRITE_PROJECT: 6,
    Permission.READ_USER_CONFIG: 8,
    Permission.NETWORK: 12,
}
_KIND_BONUS = {
    CapabilityKind.CLI_TOOL: 2,
    CapabilityKind.SKILL: 1,
    CapabilityKind.MCP: 0,
    CapabilityKind.PLUGIN: 0,
    CapabilityKind.HOOK: -1,
}


@dataclass(frozen=True)
class CandidateScore:
    fit: int
    trust: int
    risk: int
    verification: int
    kind_bonus: int

    @property
    def total(self) -> int:
        return self.fit + self.trust + self.risk + self.verification + self.kind_bonus

    def explanation(self) -> str:
        return (
            f"score={self.total} (fit={self.fit}, trust={self.trust}, risk={self.risk}, "
            f"verification={self.verification}, kind={self.kind_bonus})"
        )


def score_candidate(candidate: AdapterScanResult, requirement: str) -> CandidateScore:
    fit = 40 if requirement in candidate.manifest.provides else 0
    trust = 20 if candidate.manifest.verified else 0
    permission_cost = sum(_PERMISSION_COST[item] for item in candidate.manifest.permissions)
    risk = max(0, 30 - permission_cost)
    verification = 10 if candidate.verification.verified else 0
    return CandidateScore(
        fit=fit,
        trust=trust,
        risk=risk,
        verification=verification,
        kind_bonus=_KIND_BONUS[candidate.manifest.kind],
    )
