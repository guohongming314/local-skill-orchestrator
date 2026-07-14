from __future__ import annotations

import hashlib

import pytest

from vibe.remote.models import CapabilityKind, RemoteCandidate, SourceTier
from vibe.remote.provenance import (
    DigestMismatchError,
    PermissionLevel,
    PublisherVerifier,
    verify_candidate,
)


def candidate(*, digest: str, publisher: str | None = "Example, Inc.") -> RemoteCandidate:
    return RemoteCandidate(
        candidate_ref="npm:@example/catalog-server@1.2.3",
        name="io.example/catalog-server",
        kind=CapabilityKind.MCP_SERVER,
        version="1.2.3",
        digest=digest,
        publisher=publisher,
        source_tier=SourceTier.OFFICIAL,
    )


def test_digest_mismatch_rejects_with_explainable_reason() -> None:
    artifact = b"tampered fixture artifact"
    expected = "sha256:" + hashlib.sha256(b"original fixture artifact").hexdigest()

    with pytest.raises(DigestMismatchError, match="content digest mismatch") as raised:
        verify_candidate(
            candidate(digest=expected),
            artifact,
            source_id="io.modelcontextprotocol.registry",
            publishers=PublisherVerifier(allowlist=frozenset({"Example, Inc."})),
        )

    assert expected in str(raised.value)
    assert hashlib.sha256(artifact).hexdigest() in str(raised.value)


def test_unverifiable_publisher_of_executable_content_flags_l4() -> None:
    artifact = b"verified fixture bytes"
    digest = "sha256:" + hashlib.sha256(artifact).hexdigest()

    verified = verify_candidate(
        candidate(digest=digest, publisher="Unknown Publisher"),
        artifact,
        source_id="io.modelcontextprotocol.registry",
        publishers=PublisherVerifier(),
    )

    assert verified.provenance is not None
    assert verified.provenance.digest_verified is True
    assert verified.provenance.publisher_verified is False
    assert verified.provenance.permission_level is PermissionLevel.L4
    assert "publisher identity could not be established" in verified.provenance.reason


def test_allowlisted_and_org_signed_publishers_have_distinct_verified_provenance() -> None:
    artifact = b"verified fixture bytes"
    digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
    verifier = PublisherVerifier(
        allowlist=frozenset({"Allowlisted Publisher"}),
        signed_organizations=frozenset({"Signed Organization"}),
    )

    allowlisted = verify_candidate(
        candidate(digest=digest, publisher="Allowlisted Publisher"),
        artifact,
        source_id="io.modelcontextprotocol.registry",
        publishers=verifier,
    )
    signed = verify_candidate(
        candidate(digest=digest, publisher="Signed Organization"),
        artifact,
        source_id="io.modelcontextprotocol.registry",
        publishers=verifier,
    )

    assert allowlisted.provenance is not None
    assert signed.provenance is not None
    assert allowlisted.provenance.publisher_verified is True
    assert allowlisted.provenance.publisher_verification == "allowlist"
    assert allowlisted.provenance.permission_level is PermissionLevel.L2
    assert signed.provenance.publisher_verified is True
    assert signed.provenance.publisher_verification == "org-signature"
    assert signed.provenance.permission_level is PermissionLevel.L2
