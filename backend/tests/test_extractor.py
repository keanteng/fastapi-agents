from __future__ import annotations

import asyncio

from tests.conftest import ScriptedTestModel, wait_for_status


def test_extract_tool_in_generalist_run(client, agent_model) -> None:
    agent_model(
        ScriptedTestModel(
            call_tools="all",
            tool_args={
                "extract_entities": {
                    "text": "Satya Nadella runs Microsoft from Redmond."
                }
            },
        )
    )
    r = client.post(
        "/api/v1/runs",
        json={
            "agent": "generalist",
            "input": "Extract the entities from: Satya Nadella runs Microsoft from Redmond.",
            "tools": ["extract_entities"],
        },
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    body = wait_for_status(client, run_id, "completed")
    steps = [s for s in body["steps"] if s["type"] == "tool_call"]
    assert any(s["name"] == "extract_entities" for s in steps)
    assert body["artifacts"], "expected an output artifact"
    assert body["artifacts"][0]["kind"] == "text"
    assert body["artifacts"][0]["data"]


def test_extraction_subagent_returns_structured_output() -> None:
    from app.agents.build import build_agent
    from app.agents.extraction import EXTRACTION_DEFINITION
    from app.agents.models.extraction import ExtractionResult

    agent = build_agent(EXTRACTION_DEFINITION, tools={})

    async def _run() -> ExtractionResult:
        async with agent:
            result = await agent.run("Satya Nadella runs Microsoft from Redmond.")
        return result.output

    output = asyncio.run(_run())
    assert isinstance(output, ExtractionResult)
    data = output.model_dump()
    assert set(data) >= {"entities", "language", "summary"}
    assert isinstance(output.model_dump_json(), str)
