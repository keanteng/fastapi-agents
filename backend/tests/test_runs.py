from __future__ import annotations

import time

from tests.conftest import wait_for_status


def test_create_run_returns_202_pending(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hello"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    assert body["run_id"]
    assert body["conversation_id"] is None
    assert body["steps"] == []
    assert body["artifacts"] == []
    assert body["usage"] is None
    assert body["error"] is None


def test_create_run_unknown_agent(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "nope", "input": "hi"})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "unknown_agent"
    assert "nope" in error["message"]


def test_create_run_validation_error(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": ""})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation_error"
    assert any(e["loc"] == ["body", "input"] for e in error["details"])


def test_max_steps_bounds_rejected(client) -> None:
    r = client.post(
        "/api/v1/runs", json={"agent": "generalist", "input": "hi", "max_steps": 21}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_run_lifecycle_to_completed(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hello"})
    run_id = r.json()["run_id"]
    body = wait_for_status(client, run_id, "completed")
    assert body["status"] == "completed"
    assert body["artifacts"][0]["kind"] == "text"
    assert body["usage"]["requests"] >= 1
    assert body["started_at"] is not None
    assert body["finished_at"] is not None


def test_list_runs_most_recent_first(client) -> None:
    r1 = client.post("/api/v1/runs", json={"agent": "generalist", "input": "one"})
    time.sleep(0.05)
    r2 = client.post("/api/v1/runs", json={"agent": "generalist", "input": "two"})
    resp = client.get("/api/v1/runs")
    assert resp.status_code == 200
    runs = resp.json()
    ids = [run["run_id"] for run in runs]
    assert ids[0] == r2.json()["run_id"]
    assert ids[1] == r1.json()["run_id"]


def test_get_run_404(client) -> None:
    r = client.get("/api/v1/runs/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "run_not_found"
