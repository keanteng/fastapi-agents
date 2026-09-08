from __future__ import annotations

import json

from app.core.config import settings
from app.documents.schemas import ComplianceReport
from app.documents.storage import save_upload
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


class FakeJudge:
    async def judge(self, prompt: str) -> ComplianceReport:
        return ComplianceReport(
            overall_compliant=True,
            risk_level="low",
            summary="No issues found.",
        )


def test_document_compliance_tool_streams_and_completes(
    client, agent_model, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))

    # Fake the LLM judge so the pipeline is fully offline.
    import app.documents.tools as tools_module
    from app.documents.service import ComplianceService

    def _fake_service(**overrides):
        return ComplianceService(judge=FakeJudge(), **overrides)

    monkeypatch.setattr(tools_module, "build_compliance_service", _fake_service)

    upload_id = save_upload(
        file_name="note.txt",
        content_type="text/plain",
        data=b"Everything is fine here.",
    )["upload_id"]

    agent_model(
        ScriptedTestModel(
            call_tools=["check_compliance"],
            tool_args={"check_compliance": {"upload_id": upload_id}},
            custom_output_text="The document is compliant.",
        )
    )
    r = client.post(
        "/api/v1/runs", json={"agent": "generalist", "input": "check compliance"}
    )
    run = wait_for_status(client, r.json()["run_id"], "completed")
    conversation_id = run["conversation_id"]
    assert conversation_id

    run_body = client.get(f"/api/v1/runs/{run['run_id']}").json()
    step = next(s for s in run_body["steps"] if s["type"] == "tool_call")
    assert step["name"] == "check_compliance"
    assert step["tool_call_id"]
    assert any(s["type"] == "progress" for s in run_body["steps"])

    with client.stream("GET", f"/api/v1/runs/{run['run_id']}/events") as resp:
        frames = _parse_frames([ln for ln in resp.iter_lines() if ln])

    started = [
        f
        for f in frames
        if f["event"] == "run.tool.started"
        and f["data"]["data"].get("tool_call_id") == step["tool_call_id"]
    ]
    assert started, "expected run.tool.started for check_compliance"

    detail = client.get(f"/api/v1/conversations/{conversation_id}")
    assert detail.status_code == 200
    parts = [part for msg in detail.json()["messages"] for part in msg["parts"]]
    tool_parts = [p for p in parts if p["tool_name"] == "check_compliance"]
    assert any(p["kind"].endswith("tool-call") for p in tool_parts)
    assert any("overall_compliant" in json.dumps(p["tool_result"]) for p in tool_parts if p["kind"].endswith("tool-return"))
