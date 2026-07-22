"""Remote discovery source adapters with normalized diagnostics."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Protocol, cast

from vibe.remote.discovery import SourceDiagnostic, SourceStatus
from vibe.remote.models import CapabilityKind, RemoteCandidate, SourceTier


class SourceRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class SourceTransport(Protocol):
    def get_json(self, url: str, *, params: Mapping[str, str]) -> Mapping[str, Any]: ...

    def get_text(self, url: str, *, params: Mapping[str, str]) -> str: ...


class GitHubSource:
    source_id = "github"

    def __init__(self, *, transport: SourceTransport, per_page: int = 10) -> None:
        self._transport = transport
        self._per_page = per_page

    def search(self, capability_id: str) -> SourceDiagnostic:
        try:
            payload = self._transport.get_json(
                "https://api.github.com/search/repositories",
                params={
                    "q": f"{capability_id} agent skill in:name,description,readme",
                    "per_page": str(self._per_page),
                },
            )
            records = payload.get("items", ())
            if not isinstance(records, list):
                raise SourceRequestError("GitHub search response has no items list")
            candidates = tuple(
                self._normalize(record, capability_id)
                for record in records
                if isinstance(record, Mapping) and not bool(record.get("fork", False))
            )
            return SourceDiagnostic(
                source_id=self.source_id,
                status=SourceStatus.SUCCESS,
                candidates=candidates,
                matched_count=len(records),
            )
        except Exception as exc:
            return _failure(self.source_id, exc)

    @staticmethod
    def _normalize(record: Mapping[str, Any], capability_id: str) -> RemoteCandidate:
        full_name = _required_text(record, "full_name")
        repository = str(record.get("html_url") or f"https://github.com/{full_name}")
        owner = record.get("owner")
        publisher = (
            str(owner.get("login"))
            if isinstance(owner, Mapping)
            else full_name.split("/")[0]
        )
        return RemoteCandidate(
            candidate_ref=f"github:{full_name}@{record.get('default_branch', 'HEAD')}",
            name=str(record.get("name") or full_name.rsplit("/", 1)[-1]),
            kind=_guess_kind(record),
            provides=(capability_id,),
            publisher=publisher,
            source_tier=SourceTier.COMMUNITY,
            canonical_repository=repository.rstrip("/"),
            revision=str(record.get("default_branch") or "HEAD"),
            description=_optional_text(record.get("description")),
            stars=_nonnegative_int(record.get("stargazers_count")),
            forks=_nonnegative_int(record.get("forks_count")),
            last_activity=_optional_text(record.get("pushed_at")),
            archived=bool(record.get("archived", False)),
            official=isinstance(owner, Mapping) and owner.get("type") == "Organization",
        )


class SkillsShSource:
    source_id = "skills.sh"

    def __init__(self, *, transport: SourceTransport) -> None:
        self._transport = transport

    def search(self, capability_id: str) -> SourceDiagnostic:
        try:
            html = self._transport.get_text(
                "https://skills.sh/search", params={"q": capability_id}
            )
            records = _skills_records(html)
            tokens = _query_tokens(capability_id)
            matched = tuple(
                record
                for record in records
                if tokens.intersection(
                    _query_tokens(
                        " ".join(
                            str(record.get(key, ""))
                            for key in ("name", "skillId", "source")
                        )
                    )
                )
            )
            candidates = tuple(self._normalize(record, capability_id) for record in matched[:20])
            return SourceDiagnostic(
                source_id=self.source_id,
                status=SourceStatus.SUCCESS,
                candidates=candidates,
                matched_count=len(matched),
            )
        except Exception as exc:
            return _failure(self.source_id, exc)

    @staticmethod
    def _normalize(record: Mapping[str, Any], capability_id: str) -> RemoteCandidate:
        source = _required_text(record, "source")
        skill_id = _required_text(record, "skillId")
        return RemoteCandidate(
            candidate_ref=f"skills.sh:{source}/{skill_id}",
            name=str(record.get("name") or skill_id),
            kind=CapabilityKind.AGENT_SKILL,
            provides=(capability_id,),
            publisher=source.split("/", 1)[0],
            source_tier=(
                SourceTier.VERIFIED_PUBLISHER
                if bool(record.get("isOfficial", False))
                else SourceTier.COMMUNITY
            ),
            canonical_repository=f"https://github.com/{source}",
            cross_source_ref=f"github:{source}",
            adoption=_nonnegative_int(record.get("installs")),
            weekly_adoption=sum(
                _nonnegative_int(item)
                for item in cast(list[object], record.get("weeklyInstalls", []))
            )
            if isinstance(record.get("weeklyInstalls"), list)
            else 0,
            official=bool(record.get("isOfficial", False)),
        )


class JsonCatalogSource:
    def __init__(self, *, source_id: str, base_url: str, transport: SourceTransport) -> None:
        self.source_id = source_id
        self._base_url = base_url
        self._transport = transport

    def search(self, capability_id: str) -> SourceDiagnostic:
        try:
            payload = self._transport.get_json(
                self._base_url, params={"capability": capability_id}
            )
            records = payload.get("candidates", ())
            if not isinstance(records, list):
                raise SourceRequestError("catalog response has no candidates list")
            candidates = tuple(
                RemoteCandidate.model_validate(record)
                for record in records
                if isinstance(record, Mapping)
            )
            return SourceDiagnostic(
                source_id=self.source_id,
                status=SourceStatus.SUCCESS,
                candidates=candidates,
                matched_count=len(records),
            )
        except Exception as exc:
            return _failure(self.source_id, exc)


def _failure(source_id: str, error: Exception) -> SourceDiagnostic:
    status_code = getattr(error, "status_code", None)
    if status_code == 401:
        status = SourceStatus.UNAUTHORIZED
    elif status_code in {403, 429}:
        status = SourceStatus.RATE_LIMITED
    else:
        status = SourceStatus.FAILED
    return SourceDiagnostic(source_id=source_id, status=status, message=str(error))


def _skills_records(html: str) -> tuple[Mapping[str, Any], ...]:
    direct = re.findall(r"\{[^{}]{1,2000}\}", html)
    escaped = re.findall(r"\{(?:\\\"|[^{}]){1,2000}\}", html)
    records: list[Mapping[str, Any]] = []
    for raw in (*direct, *escaped):
        try:
            value = json.loads(raw.replace('\\"', '"'))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "source" in value and "skillId" in value:
            records.append(value)
    return tuple(records)


def _query_tokens(value: str) -> set[str]:
    return {item for item in re.split(r"[^a-z0-9]+", value.casefold()) if len(item) >= 3}


def _guess_kind(record: Mapping[str, Any]) -> CapabilityKind:
    text = f"{record.get('name', '')} {record.get('description', '')}".casefold()
    if "mcp" in text:
        return CapabilityKind.MCP_SERVER
    if "plugin" in text:
        return CapabilityKind.PLUGIN
    if "cli" in text:
        return CapabilityKind.CLI_TOOL
    return CapabilityKind.AGENT_SKILL


def _required_text(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SourceRequestError(f"source record is missing {key}")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _nonnegative_int(value: object) -> int:
    return max(0, value) if isinstance(value, int) and not isinstance(value, bool) else 0
