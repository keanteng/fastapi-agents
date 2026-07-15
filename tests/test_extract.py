from fastapi.testclient import TestClient


def test_extract(client: TestClient) -> None:
    r = client.post(
        "/api/v1/extract",
        json={"text": "Satya Nadella runs Microsoft from Redmond."},
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert "entities" in result
    assert "summary" in result
    assert "language" in result