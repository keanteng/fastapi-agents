from fastapi.testclient import TestClient


def test_skills_list(client: TestClient) -> None:
    r = client.get("/api/v1/skills")
    assert r.status_code == 200
    skills = r.json()
    assert set(skills) == {"summarizer", "translator", "code_reviewer"}


def test_skills_orchestrate(client: TestClient) -> None:
    r = client.post(
        "/api/v1/skills",
        json={"user_prompt": "summarise: hello world. this is a test."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["output"] == "skills-done"
    assert body["usage"]["requests"] >= 1
