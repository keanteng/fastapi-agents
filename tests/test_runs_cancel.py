from __future__ import annotations

import asyncio

from tests.conftest import ScriptedTestModel, wait_for_status


def test_cancel_pending_run_unit() -> None:
    from app.runs.models import RunRecord, RunStatus
    from app.runs.registry import RunRegistry

    async def go() -> None:
        registry = RunRegistry()
        record = RunRecord(run_id="r-pending", agent="generalist")
        registry.register(record)
        cancelled = await registry.cancel("r-pending")
        assert cancelled.status == RunStatus.CANCELLED
        assert [e.type for e in record.events] == ["run.cancelled"]

    asyncio.run(go())


def test_cancel_running_run_via_api(client, agent_model) -> None:
    async def slow_fetch(url: str, *, timeout: float = 10.0) -> str:
        await asyncio.sleep(0.5)
        return "slow-body"

    container = client.app.state.container
    container.agents.tools["fetch"] = slow_fetch
    agent_model(
        ScriptedTestModel(
            call_tools=["fetch"],
            tool_args={"fetch": {"url": "http://example.com"}},
            custom_output_text="done",
        )
    )
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "fetch it"})
    run_id = r.json()["run_id"]
    body = wait_for_status(client, run_id, "running", timeout=2.0)
    assert body["status"] == "running"

    c = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert c.status_code == 202
    assert c.json()["status"] == "cancelled"

    final = wait_for_status(client, run_id, "cancelled", timeout=2.0)
    assert final["finished_at"] is not None

    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        lines = [ln for ln in resp.iter_lines() if ln]
    assert any("event: run.cancelled" in ln for ln in lines)


def test_cancel_completed_run_conflict(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hi"})
    run_id = r.json()["run_id"]
    wait_for_status(client, run_id, "completed")
    c = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert c.status_code == 409
    assert c.json()["error"]["code"] == "cancel_conflict"


def test_cancel_unknown_run_404(client) -> None:
    c = client.post("/api/v1/runs/nope/cancel")
    assert c.status_code == 404
    assert c.json()["error"]["code"] == "run_not_found"
