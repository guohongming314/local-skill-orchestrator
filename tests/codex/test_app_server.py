from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vibe.codex.app_server import CodexAppServerClient, CodexTurnTimeoutError
from vibe.codex.events import CodexEventKind, TurnStatus
from vibe.codex.jsonrpc import JsonRpcSubprocessClient

FAKE_SERVER = Path(__file__).parents[1] / "fakes" / "fake_app_server.py"


def transport(mode: str, state_file: Path) -> JsonRpcSubprocessClient:
    return JsonRpcSubprocessClient([sys.executable, str(FAKE_SERVER), mode, str(state_file)])


@pytest.mark.anyio
async def test_initializes_and_executes_two_turns_on_one_thread(tmp_path: Path) -> None:
    async with transport("lifecycle", tmp_path / "state.json") as jsonrpc:
        client = CodexAppServerClient(jsonrpc, client_name="vibe-tests", client_version="1.2.3")
        server = await client.initialize()
        thread = await client.start_thread(cwd=tmp_path)
        first = await client.run_turn(thread.id, "first prompt")
        second = await client.run_turn(thread.id, "second prompt")

    assert server.user_agent == "fake-codex/1.0"
    assert first.turn.thread_id == thread.id
    assert second.turn.thread_id == thread.id
    assert first.turn.id != second.turn.id
    assert first.turn.status is TurnStatus.COMPLETED
    assert [event.kind for event in first.events] == [
        CodexEventKind.TURN_STARTED,
        CodexEventKind.ITEM_STARTED,
        CodexEventKind.ITEM_COMPLETED,
        CodexEventKind.TURN_COMPLETED,
    ]
    assert first.events[2].item == {"id": "item-1", "type": "agentMessage", "text": "first prompt"}


@pytest.mark.anyio
async def test_resumes_persisted_thread_after_client_restart(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    async with transport("lifecycle", state_file) as first_transport:
        first_client = CodexAppServerClient(first_transport)
        await first_client.initialize()
        created = await first_client.start_thread(cwd=tmp_path)

    async with transport("lifecycle", state_file) as second_transport:
        second_client = CodexAppServerClient(second_transport)
        await second_client.initialize()
        resumed = await second_client.resume_thread(created.id)
        result = await second_client.run_turn(resumed.id, "after restart")

    assert resumed.id == created.id
    assert result.turn.status is TurnStatus.COMPLETED
    assert result.events[2].item == {
        "id": "item-1",
        "type": "agentMessage",
        "text": "after restart",
    }


@pytest.mark.anyio
async def test_cancel_interrupts_active_turn_and_stream_completes(tmp_path: Path) -> None:
    marker = tmp_path / "interrupted.txt"
    async with transport("interrupt", marker) as jsonrpc:
        client = CodexAppServerClient(jsonrpc)
        await client.initialize()
        thread = await client.start_thread(cwd=tmp_path)
        turn = await client.start_turn(thread.id, "wait")
        await client.cancel_turn(turn)
        events = [event async for event in client.stream_events(turn)]

    assert events[-1].kind is CodexEventKind.TURN_COMPLETED
    assert events[-1].status is TurnStatus.INTERRUPTED
    assert marker.read_text() == turn.id


@pytest.mark.anyio
async def test_timeout_interrupts_active_turn_before_raising(tmp_path: Path) -> None:
    marker = tmp_path / "timed-out.txt"
    async with transport("interrupt", marker) as jsonrpc:
        client = CodexAppServerClient(jsonrpc)
        await client.initialize()
        thread = await client.start_thread(cwd=tmp_path)
        with pytest.raises(CodexTurnTimeoutError, match="timed out") as captured:
            await client.run_turn(thread.id, "wait forever", timeout=0.05)

    assert captured.value.turn_id is not None
    assert marker.read_text() == captured.value.turn_id
