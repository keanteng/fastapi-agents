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


def test_tool_started_event_precedes_step(client, agent_model) -> None:
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

    run = client.get(f"/api/v1/runs/{run_id}").json()
    step = next(s for s in run["steps"] if s["type"] == "tool_call")
    assert step["tool_call_id"]

    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as resp:
        frames = _parse_frames([ln for ln in resp.iter_lines() if ln])

    started = [
        f
        for f in frames
        if f["event"] == "run.tool.started"
        and f["data"]["data"].get("tool_call_id") == step["tool_call_id"]
    ]
    completed_steps = [
        f
        for f in frames
        if f["event"] == "run.step"
        and f["data"]["data"].get("step", {}).get("tool_call_id")
        == step["tool_call_id"]
    ]
    assert started, "expected a run.tool.started event for the tool call"
    assert completed_steps, "expected a run.step event for the tool call"
    started_seq = started[0]["data"]["sequence"]
    step_seq = completed_steps[0]["data"]["sequence"]
    assert started_seq < step_seq
    assert started[0]["data"]["data"]["name"] == "calculator"
