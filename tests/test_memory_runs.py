from __future__ import annotations

from typing import Any

from pydantic_ai.models.test import TestModel

from tests.conftest import _test_session_maker, wait_for_status


async def _read_history(conversation_id: str) -> list[Any]:
    from app.agents.memory.repository import MemoryRepository

    session = _test_session_maker()
    try:
        return await MemoryRepository(session).get(conversation_id)
    finally:
        await session.close()


def _texts(messages: list[Any]) -> list[str]:
    out = []
    for message in messages:
        for part in getattr(message, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, str):
                out.append(content)
    return out


async def test_run_persists_history(client, agent_model) -> None:
    agent_model(TestModel(call_tools=[], custom_output_text="hello there"))
    r = client.post(
        "/api/v1/runs",
        json={"agent": "generalist", "input": "hi", "conversation_id": "c-mem-1"},
    )
    assert r.status_code == 202
    body = wait_for_status(client, r.json()["run_id"], "completed")
    assert body["conversation_id"] == "c-mem-1"
    messages = await _read_history("c-mem-1")
    assert len(messages) >= 2
    texts = _texts(messages)
    assert "hi" in texts
    assert "hello there" in texts


async def test_second_run_replays_stored_history(client, agent_model) -> None:
    agent_model(TestModel(call_tools=[], custom_output_text="first-reply"))
    r1 = client.post(
        "/api/v1/runs",
        json={"agent": "generalist", "input": "one", "conversation_id": "c-replay"},
    )
    wait_for_status(client, r1.json()["run_id"], "completed")
    count1 = len(await _read_history("c-replay"))

    agent_model(TestModel(call_tools=[], custom_output_text="second-reply"))
    r2 = client.post(
        "/api/v1/runs",
        json={"agent": "generalist", "input": "two", "conversation_id": "c-replay"},
    )
    wait_for_status(client, r2.json()["run_id"], "completed")
    count2 = len(await _read_history("c-replay"))
    assert count2 > count1
    texts = _texts(await _read_history("c-replay"))
    assert "one" in texts
    assert "two" in texts


async def test_explicit_message_history_persisted(client, agent_model) -> None:
    agent_model(TestModel(call_tools=[], custom_output_text="reply"))
    r = client.post(
        "/api/v1/runs",
        json={
            "agent": "generalist",
            "input": "now",
            "conversation_id": "c-explicit",
            "message_history": [{"role": "user", "content": "explicit-turn"}],
        },
    )
    wait_for_status(client, r.json()["run_id"], "completed")
    texts = _texts(await _read_history("c-explicit"))
    assert "explicit-turn" in texts
    assert "now" in texts


def test_sync_poll_is_always_available(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hi"})
    run_id = r.json()["run_id"]
    # Even with no subscriber, polling reflects the full state.
    body = wait_for_status(client, run_id, "completed")
    assert body["run_id"] == run_id
