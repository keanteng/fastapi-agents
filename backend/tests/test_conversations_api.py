from __future__ import annotations

from tests.conftest import wait_for_status


def _start_memory_conversation(client) -> str:
    r = client.post(
        "/api/v1/runs", json={"agent": "generalist", "input": "hello there"}
    )
    run = wait_for_status(client, r.json()["run_id"], "completed")
    conversation_id = run["conversation_id"]
    assert conversation_id, "generalist run should have minted a conversation id"
    return conversation_id


def test_conversation_list_get_delete(client) -> None:
    conversation_id = _start_memory_conversation(client)

    listed = client.get("/api/v1/conversations")
    assert listed.status_code == 200
    summaries = listed.json()
    assert any(c["conversation_id"] == conversation_id for c in summaries)
    mine = next(c for c in summaries if c["conversation_id"] == conversation_id)
    assert mine["message_count"] >= 1
    assert mine["preview"] == "hello there"
    assert mine["updated_at"]

    detail = client.get(f"/api/v1/conversations/{conversation_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["conversation_id"] == conversation_id
    roles = [part["role"] for msg in body["messages"] for part in msg["parts"]]
    assert "user" in roles
    assert "assistant" in roles

    deleted = client.delete(f"/api/v1/conversations/{conversation_id}")
    assert deleted.status_code == 204

    gone = client.get(f"/api/v1/conversations/{conversation_id}")
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "conversation_not_found"


def test_conversation_unknown_404(client) -> None:
    detail = client.get("/api/v1/conversations/nope")
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "conversation_not_found"

    deleted = client.delete("/api/v1/conversations/nope")
    assert deleted.status_code == 404
