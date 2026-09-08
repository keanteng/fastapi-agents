from __future__ import annotations

from tests.conftest import wait_for_status


def test_extractor_structured_artifact(client) -> None:
    r = client.post(
        "/api/v1/runs",
        json={
            "agent": "extractor",
            "input": "Satya Nadella runs Microsoft from Redmond.",
        },
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    body = wait_for_status(client, run_id, "completed")
    assert body["artifacts"][0]["kind"] == "structured_output"
    data = body["artifacts"][0]["data"]
    assert set(data) >= {"entities", "language", "summary"}
