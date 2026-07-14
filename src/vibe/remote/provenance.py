"""Deterministic verification of remote artifact provenance."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path

from vibe.remote.models import (
    CapabilityKind,
    PermissionLevel,
    Provenance,
    PublisherVerification,
    RemoteCandidate,
    SourceTier,
)

__all__ = [
    "DigestMismatchError",
    "PermissionLevel",
    "ProvenanceError",
    "PublisherVerifier",
    "verify_candidate",
]


class ProvenanceError(ValueError):
    """A remote candidate cannot be given trustworthy provenance."""


class DigestMismatchError(ProvenanceError):
    """Fetched bytes do not match the source-declared content digest."""


@dataclass(frozen=True)
class PublisherVerifier:
    """Configured publisher evidence supplied by source-specific adapters."""

    allowlist: frozenset[str] = frozenset()
    signed_organizations: frozenset[str] = frozenset()

    def verify(self, publisher: str | None) -> PublisherVerification:
        if publisher is None:
            return PublisherVerification.UNVERIFIED
        if publisher in self.allowlist:
            return PublisherVerification.ALLOWLIST
        if publisher in self.signed_organizations:
            return PublisherVerification.ORG_SIGNATURE
        return PublisherVerification.UNVERIFIED


def verify_candidate(
    candidate: RemoteCandidate,
    artifact: bytes | Path,
    *,
    source_id: str,
    publishers: PublisherVerifier,
    executable: bool | None = None,
) -> RemoteCandidate:
    """Verify fetched content and attach lockfile-ready provenance.

    Publisher signatures are intentionally passed in as already validated source
    evidence. This module never treats an unverified publisher claim as proof.
    """

    content = artifact.read_bytes() if isinstance(artifact, Path) else artifact
    actual_digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    declared_digest = candidate.digest
    if declared_digest is None:
        raise ProvenanceError(f"candidate {candidate.candidate_ref!r} has no declared digest")
    if not _digest_matches(declared_digest, content):
        raise DigestMismatchError(
            "content digest mismatch for "
            f"{candidate.candidate_ref!r}: expected {declared_digest}, got {actual_digest}"
        )

    publisher_verification = publishers.verify(candidate.publisher)
    publisher_verified = publisher_verification is not PublisherVerification.UNVERIFIED
    contains_executable = _is_executable(candidate.kind) if executable is None else executable
    if contains_executable and not publisher_verified:
        permission_level = PermissionLevel.L4
        reason = "publisher identity could not be established for executable content"
    elif contains_executable:
        permission_level = PermissionLevel.L2
        reason = "content digest and publisher identity verified"
    else:
        permission_level = PermissionLevel.L1
        reason = (
            "content digest and publisher identity verified"
            if publisher_verified
            else "content digest verified; publisher identity is unverified"
        )

    provenance = Provenance(
        source=source_id,
        publisher=candidate.publisher,
        digest=actual_digest,
        source_verified=candidate.source_tier
        in {SourceTier.OFFICIAL, SourceTier.VERIFIED_PUBLISHER},
        publisher_verified=publisher_verified,
        publisher_verification=publisher_verification,
        digest_verified=True,
        permission_level=permission_level,
        reason=reason,
    )
    return candidate.model_copy(update={"provenance": provenance})


def _digest_matches(declared: str, content: bytes) -> bool:
    algorithm, separator, encoded = declared.partition(":")
    if not separator:
        raise ProvenanceError(f"unsupported content digest format: {declared!r}")
    normalized_algorithm = algorithm.lower().replace("-", "")
    if normalized_algorithm != "sha256":
        raise ProvenanceError(f"unsupported content digest algorithm: {algorithm!r}")

    raw_digest = hashlib.sha256(content).digest()
    hexadecimal = raw_digest.hex()
    if len(encoded) == len(hexadecimal):
        return hmac.compare_digest(encoded.lower(), hexadecimal)
    try:
        supplied = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ProvenanceError(f"invalid sha256 content digest: {declared!r}") from error
    return hmac.compare_digest(supplied, raw_digest)


def _is_executable(kind: CapabilityKind) -> bool:
    return kind in {CapabilityKind.MCP_SERVER, CapabilityKind.PLUGIN, CapabilityKind.CLI_TOOL}
