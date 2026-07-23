from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from vibe.remote.discovery import SourceStatus
from vibe.remote.sources import (
    GitHubSource,
    JsonCatalogSource,
    McpRegistrySource,
    SkillsShSource,
    SourceRequestError,
)


class FixtureTransport:
    def __init__(
        self,
        *,
        json_payloads: Mapping[str, Mapping[str, Any]] | None = None,
        text_payloads: Mapping[str, str] | None = None,
        failures: Mapping[str, SourceRequestError] | None = None,
    ) -> None:
        self.json_payloads = dict(json_payloads or {})
        self.text_payloads = dict(text_payloads or {})
        self.failures = dict(failures or {})
        self.requests: list[str] = []

    def get_json(self, url: str, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        key = f"{url}?" + "&".join(f"{name}={value}" for name, value in sorted(params.items()))
        self.requests.append(key)
        if key in self.failures:
            raise self.failures[key]
        return self.json_payloads[key]

    def get_text(self, url: str, *, params: Mapping[str, str]) -> str:
        key = f"{url}?" + "&".join(f"{name}={value}" for name, value in sorted(params.items()))
        self.requests.append(key)
        if key in self.failures:
            raise self.failures[key]
        return self.text_payloads[key]


def test_github_source_normalizes_popularity_and_repository_identity() -> None:
    url = "https://api.github.com/search/repositories"
    transport = FixtureTransport(
        json_payloads={
            f"{url}?per_page=10&q=browser.validation agent skill in:name,description,readme": {
                "items": [
                    {
                        "full_name": "example/browser-skill",
                        "name": "browser-skill",
                        "html_url": "https://github.com/example/browser-skill",
                        "description": "Browser validation agent skill",
                        "stargazers_count": 4200,
                        "forks_count": 220,
                        "archived": False,
                        "pushed_at": "2026-07-01T00:00:00Z",
                        "default_branch": "main",
                        "owner": {"login": "example", "type": "Organization"},
                    }
                ]
            }
        }
    )

    diagnostic = GitHubSource(transport=transport).search("browser.validation")

    assert diagnostic.status is SourceStatus.SUCCESS
    item = diagnostic.candidates[0]
    assert item.canonical_repository == "https://github.com/example/browser-skill"
    assert item.stars == 4200
    assert item.forks == 220
    assert item.publisher == "example"


def test_skills_sh_source_extracts_embedded_directory_records() -> None:
    record = {
        "source": "example/browser-skills",
        "skillId": "browser-validation",
        "name": "browser-validation",
        "installs": 12000,
        "weeklyInstalls": [100, 200],
        "isOfficial": True,
    }
    transport = FixtureTransport(
        json_payloads={
            "https://skills.sh/api/search?limit=100&q=browser.validation": {
                "skills": [record]
            }
        }
    )

    diagnostic = SkillsShSource(transport=transport).search("browser.validation")

    assert diagnostic.status is SourceStatus.SUCCESS
    item = diagnostic.candidates[0]
    assert item.name == "browser-validation"
    assert item.adoption == 12000
    assert item.canonical_repository == "https://github.com/example/browser-skills"


def test_skills_sh_source_handles_escaped_next_payload() -> None:
    escaped = (
        r'<script>self.__next_f.push("{\"source\":\"example/browser-skills\",'
        r'\"skillId\":\"browser-validation\",\"name\":\"browser-validation\",'
        r'\"installs\":9000}")</script>'
    )
    api_key = "https://skills.sh/api/search?limit=100&q=browser.validation"
    transport = FixtureTransport(
        text_payloads={"https://skills.sh/search?q=browser.validation": escaped},
        failures={api_key: SourceRequestError("API unavailable", status_code=500)},
    )

    diagnostic = SkillsShSource(transport=transport).search("browser.validation")

    assert diagnostic.status is SourceStatus.SUCCESS
    assert diagnostic.candidates[0].adoption == 9000


@pytest.mark.parametrize("html", ["", "<html><body>temporarily unavailable</body></html>"])
def test_skills_sh_source_reports_unparseable_fallback_as_failed(html: str) -> None:
    api_key = "https://skills.sh/api/search?limit=100&q=browser.validation"
    transport = FixtureTransport(
        text_payloads={"https://skills.sh/search?q=browser.validation": html},
        failures={api_key: SourceRequestError("API unavailable", status_code=500)},
    )

    diagnostic = SkillsShSource(transport=transport).search("browser.validation")

    assert diagnostic.status is SourceStatus.FAILED
    assert diagnostic.message is not None
    assert "fallback" in diagnostic.message.casefold()
    if html:
        assert html not in diagnostic.message


def test_skills_sh_valid_empty_api_result_is_successful_no_results() -> None:
    transport = FixtureTransport(
        json_payloads={
            "https://skills.sh/api/search?limit=100&q=browser.validation": {
                "skills": []
            }
        }
    )

    diagnostic = SkillsShSource(transport=transport).search("browser.validation")

    assert diagnostic.status is SourceStatus.SUCCESS
    assert diagnostic.matched_count == 0
    assert diagnostic.candidates == ()


def test_json_catalog_source_supports_organization_registry() -> None:
    url = "https://catalog.example.test/capabilities"
    transport = FixtureTransport(
        json_payloads={
            f"{url}?capability=browser.validation": {
                "candidates": [
                    {
                        "candidate_ref": "org:browser@1",
                        "name": "org-browser",
                        "kind": "agent-skill",
                        "provides": ["browser.validation"],
                        "source_tier": 8,
                    }
                ]
            }
        }
    )

    diagnostic = JsonCatalogSource(
        source_id="org", base_url=url, transport=transport
    ).search("browser.validation")

    assert diagnostic.status is SourceStatus.SUCCESS
    assert diagnostic.candidates[0].candidate_ref == "org:browser@1"


def test_mcp_registry_source_normalizes_official_server_records() -> None:
    url = "https://registry.modelcontextprotocol.io/v0.1/servers"
    transport = FixtureTransport(
        json_payloads={
            f"{url}?search=browser.validation": {
                "servers": [
                    {
                        "server": {
                            "name": "io.github.example/browser-mcp",
                            "description": "Browser automation",
                            "repository": {
                                "url": "https://github.com/example/browser-mcp"
                            },
                            "version": "1.2.3",
                            "packages": [
                                {
                                    "registryType": "npm",
                                    "identifier": "browser-mcp",
                                    "version": "1.2.3",
                                    "transport": {"type": "stdio"},
                                }
                            ],
                        },
                        "_meta": {
                            "io.modelcontextprotocol.registry/official": {
                                "isLatest": True,
                                "updatedAt": "2026-07-20T00:00:00Z",
                            }
                        },
                    }
                ]
            }
        }
    )

    diagnostic = McpRegistrySource(transport=transport).search("browser.validation")

    assert diagnostic.status is SourceStatus.SUCCESS
    item = diagnostic.candidates[0]
    assert item.name == "io.github.example/browser-mcp"
    assert item.official is True
    assert item.canonical_repository == "https://github.com/example/browser-mcp"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, SourceStatus.UNAUTHORIZED),
        (403, SourceStatus.RATE_LIMITED),
        (429, SourceStatus.RATE_LIMITED),
        (500, SourceStatus.FAILED),
    ],
)
def test_source_request_failures_are_classified(status_code: int, expected: SourceStatus) -> None:
    url = "https://api.github.com/search/repositories"
    key = f"{url}?per_page=10&q=browser.validation agent skill in:name,description,readme"
    transport = FixtureTransport(
        failures={key: SourceRequestError("request failed", status_code=status_code)}
    )

    diagnostic = GitHubSource(transport=transport).search("browser.validation")

    assert diagnostic.status is expected
    assert diagnostic.candidates == ()
