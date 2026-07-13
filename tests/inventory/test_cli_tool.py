from __future__ import annotations

from collections.abc import Sequence

from vibe.inventory.adapters.cli_tool import CliToolAdapter, CliToolSpec, ProbeResult
from vibe.inventory.service import InventoryService
from vibe.models.capability import CapabilityScope, Permission


def specs() -> tuple[CliToolSpec, ...]:
    return (
        CliToolSpec("git", "git", ("--version",), ("version-control",)),
        CliToolSpec("rg", "rg", ("--version",), ("search-code",)),
        CliToolSpec("python", "python", ("--version",), ("python-runtime",)),
        CliToolSpec("pytest", "pytest", ("--version",), ("run-python-tests",)),
    )


def test_configured_tools_report_normalized_versions_without_shell_interpolation() -> None:
    calls: list[tuple[str, ...]] = []
    versions = {
        "git": "git version 2.50.1.windows.1\n",
        "rg": "ripgrep 14.1.1\n-SIMD",
        "python": "Python 3.12.10",
        "pytest": "pytest 8.4.1",
    }

    def resolve(executable: str) -> str | None:
        return f"/tools/{executable}"

    def probe(argv: Sequence[str]) -> ProbeResult:
        calls.append(tuple(argv))
        return ProbeResult(returncode=0, stdout=versions[argv[0].rsplit("/", 1)[-1]], stderr="")

    inventory = InventoryService().scan(
        [CliToolAdapter(specs=specs(), executable_resolver=resolve, probe_runner=probe)]
    )

    assert [(item.manifest.name, item.manifest.version) for item in inventory.capabilities] == [
        ("git", "2.50.1.windows.1"),
        ("pytest", "8.4.1"),
        ("python", "3.12.10"),
        ("rg", "14.1.1"),
    ]
    assert calls == [
        ("/tools/git", "--version"),
        ("/tools/pytest", "--version"),
        ("/tools/python", "--version"),
        ("/tools/rg", "--version"),
    ]
    assert all(item.manifest.scope is CapabilityScope.SYSTEM for item in inventory.capabilities)
    assert all(
        item.manifest.permissions == frozenset({Permission.EXECUTE_COMMAND})
        for item in inventory.capabilities
    )


def test_unavailable_and_failed_probes_are_recorded_without_aborting_inventory() -> None:
    def resolve(executable: str) -> str | None:
        return None if executable == "missing" else f"/tools/{executable}"

    def probe(argv: Sequence[str]) -> ProbeResult:
        if argv[0].endswith("broken"):
            return ProbeResult(returncode=2, stdout="", stderr="probe failed")
        return ProbeResult(returncode=0, stdout="healthy 1.2.3", stderr="")

    adapter = CliToolAdapter(
        specs=(
            CliToolSpec("missing", "missing", ("--version",), ("missing-capability",)),
            CliToolSpec("broken", "broken", ("--version",), ("broken-capability",)),
            CliToolSpec("healthy", "healthy", ("--version",), ("healthy-capability",)),
        ),
        executable_resolver=resolve,
        probe_runner=probe,
    )

    inventory = InventoryService().scan([adapter])

    assert inventory.diagnostics == ()
    by_name = {item.manifest.name: item for item in inventory.capabilities}
    assert by_name["healthy"].manifest.verified
    assert by_name["healthy"].manifest.version == "1.2.3"
    assert not by_name["missing"].manifest.verified
    assert by_name["missing"].verification.details == ("unavailable:missing",)
    assert not by_name["broken"].manifest.verified
    assert by_name["broken"].verification.details == ("probe_failed:exit=2:probe failed",)


def test_probe_exception_is_contained_as_unverifiable_tool() -> None:
    def probe(argv: Sequence[str]) -> ProbeResult:
        raise OSError("access denied")

    adapter = CliToolAdapter(
        specs=(CliToolSpec("git", "git", ("--version",), ("version-control",)),),
        executable_resolver=lambda executable: f"/tools/{executable}",
        probe_runner=probe,
    )

    result = adapter.scan(adapter.discover()[0])

    assert not result.verification.verified
    assert result.verification.details == ("probe_error:OSError:access denied",)
