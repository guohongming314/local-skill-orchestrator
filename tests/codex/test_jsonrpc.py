from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import anyio
import pytest

from vibe.codex.jsonrpc import JsonRpcSubprocessClient
from vibe.codex.protocol import (
    JsonRpcEOFError,
    JsonRpcMalformedMessageError,
    JsonRpcProcessError,
    JsonRpcRemoteError,
    JsonRpcTimeoutError,
)

FAKE_SERVER = Path(__file__).parents[1] / "fakes" / "fake_app_server.py"


def command(scenario: str) -> list[str]:
    return [sys.executable, str(FAKE_SERVER), scenario]


@pytest.mark.anyio
async def test_concurrent_requests_receive_matching_out_of_order_responses() -> None:
    async with JsonRpcSubprocessClient(command("concurrent")) as client:
        results: dict[str, Any] = {}

        async def call(name: str) -> None:
            results[name] = await client.request("echo", {"value": name})

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(call, "first")
            await anyio.sleep(0.02)
            task_group.start_soon(call, "second")

    assert results == {"first": {"echo": "first"}, "second": {"echo": "second"}}


@pytest.mark.anyio
async def test_routes_notifications_and_server_requests() -> None:
    async with JsonRpcSubprocessClient(command("routes")) as client:
        async with anyio.create_task_group() as task_group:
            result: dict[str, Any] = {}

            async def call() -> None:
                result["value"] = await client.request("begin", {})

            task_group.start_soon(call)
            notification = await client.receive_notification()
            server_request = await client.receive_server_request()
            await client.respond(server_request.id, {"decision": "accept"})

        assert notification.method == "turn/started"
        assert notification.params == {"turnId": "turn-1"}
        assert server_request.method == "item/commandExecution/requestApproval"
        assert result["value"] == {
            "serverResponse": {"id": 9001, "result": {"decision": "accept"}}
        }


@pytest.mark.anyio
async def test_malformed_output_is_a_typed_actionable_error() -> None:
    async with JsonRpcSubprocessClient(command("malformed")) as client:
        with pytest.raises(JsonRpcMalformedMessageError, match="not valid JSON"):
            await client.request("test", {})


@pytest.mark.anyio
async def test_eof_before_response_is_a_typed_error() -> None:
    async with JsonRpcSubprocessClient(command("eof")) as client:
        with pytest.raises(JsonRpcEOFError, match="stdout closed"):
            await client.request("test", {})


@pytest.mark.anyio
async def test_nonzero_subprocess_exit_reports_code_and_stderr() -> None:
    async with JsonRpcSubprocessClient(command("crash")) as client:
        with pytest.raises(JsonRpcProcessError) as captured:
            await client.request("test", {})

    assert captured.value.returncode == 23
    assert "fatal fake app-server failure" in str(captured.value)


@pytest.mark.anyio
async def test_request_timeout_is_typed_and_identifies_method() -> None:
    async with JsonRpcSubprocessClient(command("timeout")) as client:
        with pytest.raises(JsonRpcTimeoutError, match="slow/method"):
            await client.request("slow/method", {}, timeout=0.05)


@pytest.mark.anyio
async def test_shutdown_reaps_subprocess() -> None:
    client = JsonRpcSubprocessClient(command("idle"))
    await client.start()
    assert client.pid is not None
    assert client.returncode is None

    await client.close()

    assert client.returncode is not None


@pytest.mark.anyio
async def test_remote_json_rpc_error_preserves_details() -> None:
    async with JsonRpcSubprocessClient(command("remote-error")) as client:
        with pytest.raises(JsonRpcRemoteError) as captured:
            await client.request("thread/start", {})

    assert captured.value.code == -32602
    assert captured.value.data == {"field": "cwd"}
    assert "bad params" in str(captured.value)
