from pathlib import Path

WORKFLOW = Path(".github/workflows/ci.yml")


def test_ci_workflow_covers_pull_requests_and_main_pushes() -> None:
    document = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in document
    assert "push:" in document
    assert "branches: [main]" in document
    assert 'python-version: "3.12"' in document


def test_ci_workflow_matches_the_complete_local_quality_gate() -> None:
    document = WORKFLOW.read_text(encoding="utf-8")

    commands = (
        "uv sync --locked --all-groups",
        "uv run pytest",
        "uv run ruff check .",
        "uv run mypy src tests",
        "uv build",
        "git diff --check",
    )
    for command in commands:
        assert f"run: {command}" in document


def test_ci_workflow_caches_only_uv_artifacts() -> None:
    document = WORKFLOW.read_text(encoding="utf-8")

    assert "astral-sh/setup-uv@" in document
    assert "enable-cache: true" in document
    assert "cache-dependency-glob: uv.lock" in document
    assert "actions/cache@" not in document