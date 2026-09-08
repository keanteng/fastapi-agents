from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic_ai import UsageLimits
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartEndEvent,
    TextPart,
)

from app.agents.memory.repository import MemoryRepository
from app.core.config import settings
from app.core.db import get_session_maker
from app.runs.events import (
    cancelled_data,
    completed_data,
    created_data,
    delta_data,
    done_data,
    failed_data,
    tool_started_data,
)
from app.runs.models import (
    ErrorBody,
    RunArtifact,
    RunMessage,
    RunRecord,
    RunStatus,
    RunStep,
    RunUsage,
    TERMINAL_STATUSES,
)

if TYPE_CHECKING:
    from app.runs.registry import RunRegistry


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def usage_limits(max_steps: int) -> UsageLimits:
    return UsageLimits(
        request_limit=max(2, max_steps * 3),
        tool_calls_limit=max(1, max_steps),
    )


def run_messages_to_model_messages(messages: list[RunMessage]) -> list[Any]:
    """Convert API ``RunMessage`` DTOs into pydantic-ai ``ModelMessage``s."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )

    converted: list[Any] = []
    for message in messages:
        if message.role == "user":
            converted.append(
                ModelRequest(
                    parts=[UserPromptPart(content=message.content, timestamp=now_utc())]
                )
            )
        else:
            converted.append(ModelResponse(parts=[TextPart(content=message.content)]))
    return converted


def classify_error(exc: Exception) -> tuple[str, str]:
    from pydantic_ai.exceptions import ToolRetryError

    message = str(exc) or exc.__class__.__name__
    if isinstance(exc, ToolRetryError) or (
        "exceeded max retries count" in message and "Tool" in message
    ):
        return "tool_error", f"tool call failed after retries: {message}"
    return "model_error", message


def make_step_handler(
    record: RunRecord, registry: Any, *, emit_message_steps: bool
) -> Any:
    """Build the ``event_stream_handler`` that records ``run.step`` events."""
    pending: dict[str, dict[str, Any]] = {}

    async def handler(_ctx: Any, events: AsyncIterable[Any]) -> None:
        async for event in events:
            if isinstance(event, FunctionToolCallEvent):
                args = event.part.args_as_dict() if event.part.args else {}
                started_at = now_utc()
                pending[event.tool_call_id] = {
                    "name": event.part.tool_name,
                    "summary": json.dumps(args, default=str)[:200],
                    "started_at": started_at,
                }
                # Additive live event so the UI can open a "tool running"
                # card as soon as the tool begins (not only when it returns).
                await registry.emit(
                    record,
                    "run.tool.started",
                    tool_started_data(
                        event.tool_call_id,
                        event.part.tool_name,
                        args,
                        started_at,
                    ),
                )
            elif isinstance(event, FunctionToolResultEvent):
                info = pending.pop(event.tool_call_id, None)
                if info is not None:
                    await registry.add_step(
                        record,
                        RunStep(
                            index=0,
                            type="tool_call",
                            name=info["name"],
                            summary=info["summary"],
                            result=str(event.part.content)[:500],
                            tool_call_id=event.tool_call_id,
                            started_at=info["started_at"],
                            finished_at=now_utc(),
                        ),
                    )
            elif (
                emit_message_steps
                and isinstance(event, PartEndEvent)
                and isinstance(event.part, TextPart)
            ):
                await registry.add_step(
                    record,
                    RunStep(
                        index=0,
                        type="message",
                        name="message",
                        summary=event.part.content[:200],
                        result=None,
                        started_at=now_utc(),
                        finished_at=now_utc(),
                    ),
                )

    return handler


async def execute_run(
    record: RunRecord, registry: "RunRegistry", container: Any, request: Any
) -> None:
    """The asyncio task body for a single run (§8.1)."""
    definition = container.agents.definitions[request.agent]

    async with registry.lock:
        if record.status == RunStatus.CANCELLED:
            return  # cancelled before the task started; cancel() emitted the terminal event
        if definition.uses_memory and record.conversation_id is None:
            record.conversation_id = uuid.uuid4().hex
        record.status = RunStatus.RUNNING
        record.started_at = now_utc()

    await registry.emit(
        record,
        "response.created",
        created_data(record.agent, record.conversation_id, request.input),
    )

    try:
        await _execute_agent(record, registry, container, request, definition)
    except asyncio.CancelledError:
        pass  # a cancel request raced us; the finally block emits run.cancelled
    except TimeoutError:
        error = ErrorBody(
            code="timeout",
            message="run exceeded RUN_TIMEOUT_SECONDS",
            details=None,
            run_id=record.run_id,
        )
        await _fail(record, registry, error)
    except Exception as exc:  # noqa: BLE001 - run-level errors are recorded, not raised
        code, message = classify_error(exc)
        error = ErrorBody(
            code=code, message=message, details=None, run_id=record.run_id
        )
        await _fail(record, registry, error)
    finally:
        async with registry.lock:
            if record.status == RunStatus.CANCELLED:
                # The run was cancelled mid-flight; no terminal event yet.
                registry._emit_locked(record, "run.cancelled", cancelled_data())
            record.task = None


async def _execute_agent(
    record: RunRecord,
    registry: "RunRegistry",
    container: Any,
    request: Any,
    definition: Any,
) -> None:
    from app.documents.tools import make_document_tools

    async def _emit_progress(message: str) -> None:
        await registry.add_progress(record, message)

    agent = container.agents.build_agent(
        request.agent,
        tools=request.tools,
        capabilities=request.capabilities,
        tool_overrides=make_document_tools(emit=_emit_progress),
    )

    history: list[Any] | None = None
    if definition.uses_memory:
        history = await _load_history(record.conversation_id)
    if request.message_history:
        history = run_messages_to_model_messages(request.message_history)

    step_handler = make_step_handler(
        record,
        registry,
        emit_message_steps=(definition.output_type == "structured_output"),
    )

    if definition.output_type == "string":
        text = ""
        all_messages: list[Any] = []
        usage: RunUsage | None = None
        async with asyncio.timeout(settings.run_timeout_seconds):
            async with agent:
                async with agent.run_stream(
                    request.input,
                    message_history=history or None,
                    usage_limits=usage_limits(request.max_steps),
                    event_stream_handler=step_handler,
                ) as stream:
                    async for delta in stream.stream_text(delta=True):
                        text += delta
                        await registry.emit(
                            record, "response.output_text.delta", delta_data(delta)
                        )
                    await registry.emit(
                        record, "response.output_text.done", done_data(text)
                    )
                    all_messages = list(stream.all_messages())
                    usage = RunUsage.from_pai(stream.usage)
        artifact = RunArtifact(name="output", kind="text", data=text)
    else:
        all_messages = []
        usage = None
        async with asyncio.timeout(settings.run_timeout_seconds):
            async with agent:
                result = await agent.run(
                    request.input,
                    message_history=history or None,
                    usage_limits=usage_limits(request.max_steps),
                    event_stream_handler=step_handler,
                )
        all_messages = list(result.all_messages())
        usage = RunUsage.from_pai(result.usage)
        artifact = RunArtifact(
            name="output", kind="structured_output", data=result.output
        )

    if definition.uses_memory:
        await _persist_history(record.conversation_id, all_messages)
    await _complete(record, registry, [artifact], usage)


async def _complete(
    record: RunRecord,
    registry: "RunRegistry",
    artifacts: list[RunArtifact],
    usage: RunUsage | None,
) -> None:
    async with registry.lock:
        if record.status in TERMINAL_STATUSES:
            return
        record.status = RunStatus.COMPLETED
        record.finished_at = now_utc()
        record.artifacts = artifacts
        record.usage = usage
        registry._emit_locked(
            record,
            "response.completed",
            completed_data(record.status.value, usage, artifacts),
        )


async def _fail(record: RunRecord, registry: "RunRegistry", error: ErrorBody) -> None:
    async with registry.lock:
        if record.status in TERMINAL_STATUSES:
            return
        record.status = RunStatus.FAILED
        record.finished_at = now_utc()
        record.error = error
        registry._emit_locked(record, "response.failed", failed_data(error))


async def _load_history(conversation_id: str | None) -> list[Any]:
    if conversation_id is None:
        return []
    session = get_session_maker()()
    try:
        return await MemoryRepository(session).get(conversation_id)
    finally:
        await session.close()


async def _persist_history(conversation_id: str | None, messages: list[Any]) -> None:
    if conversation_id is None:
        return
    session = get_session_maker()()
    try:
        await MemoryRepository(session).set(conversation_id, messages)
        await session.commit()
    finally:
        await session.close()
