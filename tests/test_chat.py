from fastapi.testclient import TestClient


def test_chat(client: TestClient) -> None:
    r = client.post("/api/v1/chat", json={"user_prompt": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == "chat-response"
    assert body["usage"]["requests"] >= 1


def test_chat_stream(client: TestClient) -> None:
    with client.stream(
        "POST", "/api/v1/chat/stream", json={"user_prompt": "hello"}
    ) as resp:
        assert resp.status_code == 200
        events = [line for line in resp.iter_lines() if line]
    # SSE frames start with ``data:``; ensure at least one arrived.
    assert any(line.startswith("data:") for line in events)
