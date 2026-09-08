from __future__ import annotations

from app.runs.models import (
    ErrorBody,
    RunMessage,
    RunRecord,
    RunResponse,
    RunStatus,
    RunStep,
    RunUsage,
)


def test_run_status_values() -> None:
    assert RunStatus.PENDING.value == "pending"
    assert RunStatus.RUNNING.value == "running"
    assert RunStatus.COMPLETED.value == "completed"
    assert RunStatus.FAILED.value == "failed"
    assert RunStatus.CANCELLED.value == "cancelled"


def test_error_body_fields() -> None:
    body = ErrorBody(code="run_not_found", message="nope", details=None, run_id="r1")
    assert body.model_dump() == {
        "code": "run_not_found",
        "message": "nope",
        "details": None,
        "run_id": "r1",
    }


def test_run_message_roles() -> None:
    user = RunMessage(role="user", content="hi")
    assistant = RunMessage(role="assistant", content="yo")
    assert user.role == "user"
    assert assistant.role == "assistant"


def test_run_usage_from_pai() -> None:
    class FakeUsage:
        input_tokens = 10
        output_tokens = 20
        requests = 3

    usage = RunUsage.from_pai(FakeUsage())
    assert usage == RunUsage(input_tokens=10, output_tokens=20, requests=3)


def test_run_record_initial_state() -> None:
    record = RunRecord(run_id="r1", agent="generalist", conversation_id=None)
    assert record.status == RunStatus.PENDING
    assert record.steps == []
    assert record.artifacts == []
    assert record.usage is None
    assert record.error is None
    assert record.seq_counter == 0
    assert record.sse_claimed is False
    assert len(record.events) == 0


def test_run_response_from_record() -> None:
    record = RunRecord(run_id="r1", agent="generalist")
    record.steps.append(
        RunStep(
            index=1,
            type="tool_call",
            name="calculator",
            summary="1+1",
            result="2",
            started_at=record.created_at,
            finished_at=record.created_at,
        )
    )
    response = RunResponse.from_record(record)
    assert response.run_id == "r1"
    assert response.status == RunStatus.PENDING
    assert len(response.steps) == 1
    assert response.steps[0].name == "calculator"
    assert response.error is None
