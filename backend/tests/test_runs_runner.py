from __future__ import annotations

import asyncio
import types
from datetime import datetime, timezone


from app.core.container import get_container
from app.runs.events import (
    RunEvent,
    cancelled_data,
    completed_data,
    created_data,
    delta_data,
    done_data,
    failed_data,
    ping_data,
    step_data,
)
from app.runs.models import (
    ErrorBody,
    RunArtifact,
    RunMessage,
    RunStatus,
    RunStep,
    RunUsage,
)
from app.runs.registry import RunRegistry
from app.runs.runner import run_messages_to_model_messages, step_budget_note


def _request(**overrides: object) -> types.SimpleNamespace:
    """Duck-typed stand-in for ``app.api.runs.CreateRunRequest``."""
    defaults = {
        "agent": "generalist",
        "input": "hello",
        "conversation_id": None,
        "message_history": None,
        "tools": None,
        "capabilities": None,
        "max_steps": 8,
        "metadata": None,
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_event_data_builders() -> None:
    assert created_data("generalist", "c1", "hi") == {
        "agent": "generalist",
        "conversation_id": "c1",
        "input": "hi",
    }
    assert delta_data("Hi") == {"delta": "Hi"}
    assert done_data("Hi") == {"text": "Hi"}
    assert cancelled_data() == {"error": None}
    assert "t" in ping_data()

    step = RunStep(
        index=1,
        type="tool_call",
        name="calculator",
        summary="1+1",
        result="2",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    assert step_data(step) == {"step": step.model_dump(mode="json")}

    error = ErrorBody(code="model_error", message="boom", details=None, run_id="r")
    assert failed_data(error)["error"]["code"] == "model_error"

    usage = RunUsage(input_tokens=1, output_tokens=2, requests=3)
    artifacts = [RunArtifact(name="output", kind="text", data="hi")]
    data = completed_data("completed", usage, artifacts)
    assert data["status"] == "completed"
    assert data["usage"]["requests"] == 3
    assert data["artifacts"][0]["data"] == "hi"


def test_run_event_terminal() -> None:
    terminal = RunEvent(
        type="response.completed",
        run_id="r",
        sequence=1,
        created_at=datetime.now(timezone.utc),
        data={},
    )
    assert terminal.terminal
    delta = RunEvent(
        type="response.output_text.delta",
        run_id="r",
        sequence=2,
        created_at=datetime.now(timezone.utc),
        data={},
    )
    assert not delta.terminal
    assert RunEvent(
        type="response.failed",
        run_id="r",
        sequence=3,
        created_at=datetime.now(timezone.utc),
        data={},
    ).terminal
    assert RunEvent(
        type="run.cancelled",
        run_id="r",
        sequence=4,
        created_at=datetime.now(timezone.utc),
        data={},
    ).terminal


def test_run_messages_conversion() -> None:
    converted = run_messages_to_model_messages(
        [
            RunMessage(role="user", content="hi"),
            RunMessage(role="assistant", content="yo"),
        ]
    )
    assert len(converted) == 2
    assert type(converted[0]).__name__ == "ModelRequest"
    assert type(converted[1]).__name__ == "ModelResponse"


def test_step_budget_note_none_when_budget_remains() -> None:
    usage = RunUsage(input_tokens=1, output_tokens=2, requests=3, tool_calls=2)
    assert step_budget_note(usage, max_steps=8) is None
    assert step_budget_note(None, max_steps=8) is None


def test_step_budget_note_when_request_budget_exhausted() -> None:
    usage = RunUsage(input_tokens=1, output_tokens=2, requests=6, tool_calls=2)
    note = step_budget_note(usage, max_steps=2)
    assert note is not None
    assert "full step budget" in note
    assert "6 model request(s)" in note


def test_step_budget_note_when_tool_call_budget_exhausted() -> None:
    usage = RunUsage(input_tokens=1, output_tokens=2, requests=4, tool_calls=16)
    note = step_budget_note(usage, max_steps=16)
    assert note is not None
    assert "16 tool call(s)" in note


async def test_runner_completes_string_run(agent_model) -> None:
    from pydantic_ai.models.test import TestModel

    agent_model(TestModel(call_tools=[], custom_output_text="hello there"))
    container = get_container()
    request = _request(agent="generalist", input="hello")
    registry = RunRegistry()
    record = await registry.create(request, container)
    assert record.task is not None
    await record.task
    assert record.status == RunStatus.COMPLETED
    assert record.started_at is not None
    assert record.finished_at is not None
    assert record.artifacts[0].kind == "text"
    assert record.usage is not None and record.usage.requests >= 1
    types_ = [e.type for e in record.events]
    assert types_[0] == "response.created"
    assert types_[-1] == "response.completed"
    assert "response.output_text.delta" in types_
    assert "response.output_text.done" in types_


async def test_runner_extract_tool_step_and_artifact(agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    agent_model(
        ScriptedTestModel(
            call_tools="all",
            tool_args={
                "extract_entities": {"text": "Satya Nadella runs Microsoft."}
            },
        )
    )
    container = get_container()
    request = _request(
        agent="generalist",
        input="extract the entities from: Satya Nadella runs Microsoft.",
        tools=["extract_entities"],
    )
    registry = RunRegistry()
    record = await registry.create(request, container)
    assert record.task is not None
    await record.task
    assert record.status == RunStatus.COMPLETED
    step_names = [s.name for s in record.steps if s.type == "tool_call"]
    assert "extract_entities" in step_names
    assert record.artifacts[0].kind == "text"
    assert record.artifacts[0].data


async def test_runner_timeout_fails_run(monkeypatch, agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    from app.core.config import settings

    monkeypatch.setattr(settings, "run_timeout_seconds", 0.05)
    container = get_container()

    async def slow_fetch(url: str, *, timeout: float = 10.0) -> str:
        await asyncio.sleep(0.5)
        return "slow-body"

    monkeypatch.setitem(container.agents.tools, "fetch", slow_fetch)
    agent_model(
        ScriptedTestModel(
            call_tools=["fetch"],
            tool_args={"fetch": {"url": "http://example.com"}},
            custom_output_text="done",
        )
    )
    request = _request(agent="generalist", input="fetch something")
    registry = RunRegistry()
    record = await registry.create(request, container)
    assert record.task is not None
    await asyncio.gather(record.task, return_exceptions=True)
    assert record.status == RunStatus.FAILED
    assert record.error is not None
    assert record.error.code == "timeout"
    assert record.events[-1].type == "response.failed"


async def test_runner_tool_error_after_retries(monkeypatch, agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    container = get_container()

    def always_fail(x: str) -> str:
        raise ValueError("nope")

    monkeypatch.setitem(container.agents.tools, "calculator", always_fail)
    agent_model(
        ScriptedTestModel(
            call_tools=["calculator"],
            tool_args={"calculator": {"expression": "1+1"}},
            custom_output_text="x",
        )
    )
    request = _request(agent="generalist", input="compute")
    registry = RunRegistry()
    record = await registry.create(request, container)
    assert record.task is not None
    await record.task
    assert record.status == RunStatus.FAILED
    assert record.error is not None
    assert record.error.code == "tool_error"
    assert record.events[-1].type == "response.failed"


async def test_runner_cancel_mid_run(monkeypatch, agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    container = get_container()

    async def slow_fetch(url: str, *, timeout: float = 10.0) -> str:
        await asyncio.sleep(0.5)
        return "slow-body"

    monkeypatch.setitem(container.agents.tools, "fetch", slow_fetch)
    agent_model(
        ScriptedTestModel(
            call_tools=["fetch"],
            tool_args={"fetch": {"url": "http://example.com"}},
            custom_output_text="done",
        )
    )
    request = _request(agent="generalist", input="fetch something")
    registry = RunRegistry()
    record = await registry.create(request, container)
    for _ in range(50):
        if record.status == RunStatus.RUNNING:
            break
        await asyncio.sleep(0.01)
    assert record.status == RunStatus.RUNNING
    cancelled = await registry.cancel(record.run_id)
    assert cancelled.status == RunStatus.CANCELLED
    assert record.task is not None
    await asyncio.gather(record.task, return_exceptions=True)
    assert record.status == RunStatus.CANCELLED
    assert record.events[-1].type == "run.cancelled"
