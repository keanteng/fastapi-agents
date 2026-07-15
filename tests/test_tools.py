from fastapi.testclient import TestClient


def test_tools(client: TestClient) -> None:
    r = client.post("/api/v1/tools", json={"user_prompt": "what is 1+1 and the time?"})
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == "tools-done"
    assert body["usage"]["requests"] >= 1