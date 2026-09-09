from __future__ import annotations

import json

from tests.conftest import ScriptedTestModel, wait_for_status


def _parse_frames(lines: list[str]) -> list[dict]:
    frames = []
    current = None
    for line in lines:
        if line.startswith("event:"):
            current = {"event": line.split(":", 1)[1].strip()}
        elif line.startswith("data:") and current is not None:
            current["data"] = json.loads(line.split(":", 1)[1].strip())
            frames.append(current)
            current = None
    return frames


def test_generalist_stream_envelope_and_order(client, agent_model) -> None:
    agent_model(
        ScriptedTestModel(
            call_tools=["calculator"],
            tool_args={"calculator": {"expression": "1+1"}},
            custom_output_text="The result is 2.",
        )
    )
    r = client.post(
        "/api/v1/runs", json={"agent": "generalist", "input": "compute 1+1"}
    )
    run_id = r.json()["run_id"]
    wait_for_status(client, run_id, "completed")

    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        lines = [ln for ln in resp.iter_lines() if ln]

    frames = _parse_frames(lines)
    types = [f["event"] for f in frames]
    assert types[0] == "response.created"
    assert types[-1] == "response.completed"
    sequences = [f["data"]["sequence"] for f in frames]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert any(
        f["event"] == "run.step" and f["data"]["data"]["step"]["name"] == "calculator"
        for f in frames
    )
    delta_idx = types.index("response.output_text.delta")
    done_idx = types.index("response.output_text.done")
    assert delta_idx < done_idx < len(types) - 1


def test_retired_extractor_agent_is_rejected(client) -> None:
    r = client.post(
        "/api/v1/runs",
        json={"agent": "extractor", "input": "Satya Nadella runs Microsoft."},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unknown_agent"


def test_stream_unknown_run_404(client) -> None:
    r = client.get("/api/v1/runs/nope/events")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "run_not_found"


def test_second_subscriber_rejected(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hi"})
    run_id = r.json()["run_id"]
    wait_for_status(client, run_id, "completed")

    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as resp:
        lines = [ln for ln in resp.iter_lines() if ln]
    assert any("response.completed" in ln for ln in lines)

    # The claim is one-shot: a later subscriber is rejected with 409.
    r2 = client.get(f"/api/v1/runs/{run_id}/events")
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "sse_busy"
