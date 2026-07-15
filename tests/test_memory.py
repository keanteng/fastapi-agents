from fastapi.testclient import TestClient


def test_memory_lifecycle(client: TestClient) -> None:
    cid = "conv-1"

    # start empty
    r = client.get(f"/api/v1/memory/{cid}")
    assert r.status_code == 200
    assert r.json() == {"conversation_id": cid, "messages": []}

    # append a stored user message
    r = client.post(f"/api/v1/memory/{cid}", json={"user_prompt": "remember this"})
    assert r.status_code == 200
    appended = r.json()
    assert appended["messages_before"] == 0
    assert appended["messages_after"] == 1

    # memory-aware chat replays history and stores the turn
    r = client.post(f"/api/v1/memory/{cid}/chat", json={"user_prompt": "what did I say?"})
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] == cid
    assert body["output"] == "memory-response"

    # history now persisted
    r = client.get(f"/api/v1/memory/{cid}")
    assert r.status_code == 200
    assert len(r.json()["messages"]) >= 2

    # clear
    r = client.delete(f"/api/v1/memory/{cid}")
    assert r.status_code == 200
    assert r.json() == {"conversation_id": cid, "cleared": True}

    # clearing again -> 404
    r = client.delete(f"/api/v1/memory/{cid}")
    assert r.status_code == 404