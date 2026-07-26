from fastapi.testclient import TestClient


def test_tasks(client: TestClient) -> None:
    r = client.post(
        "/api/v1/tasks",
        json={"goal": "greet the user and translate a sentence", "max_steps": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == "tasks-done"
    assert body["usage"]["requests"] >= 1
    assert any(s["tool"] == "delegate_chat" for s in body["steps"])
