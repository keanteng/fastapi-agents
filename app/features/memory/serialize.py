"""Stable DTO mapping for pydantic-ai ``ModelMessage`` lists.

The frontend-facing schema (``MessageOut``/``PartOut``) intentionally hides
pydantic-ai's internal part taxonomy so external clients aren't coupled to
the agent framework. The repository stores the raw payload (see
``repository.py``) so we always round-trip back to full-fidelity messages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.features.memory.schemas import MessageOut, PartOut

_PART_KIND_TO_ROLE = {
    "user-prompt": "user",
    "system-prompt": "system",
    "text": "assistant",
    "tool-call": "tool",
    "tool-return": "tool",
}


def _part_to_dto(part: Any) -> PartOut:
    kind = getattr(part, "part_kind", "unknown")
    content: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_call_id: str | None = None
    tool_result: Any | None = None
    timestamp: datetime | None = None
    role = _PART_KIND_TO_ROLE.get(kind, "unknown")

    if isinstance(part, UserPromptPart):
        c = part.content
        content = c if isinstance(c, str) else str(c)
        timestamp = part.timestamp
    elif isinstance(part, SystemPromptPart):
        content = part.content
        timestamp = part.timestamp
    elif isinstance(part, TextPart):
        content = part.content
    elif isinstance(part, ToolCallPart):
        tool_name = part.tool_name
        args = part.args
        tool_args = args if isinstance(args, dict) else None
        tool_call_id = part.tool_call_id
    elif isinstance(part, ToolReturnPart):
        tool_name = part.tool_name
        tool_call_id = part.tool_call_id
        tool_result = part.content
        timestamp = part.timestamp

    return PartOut(
        kind=str(kind),
        role=role,
        content=content,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_call_id=tool_call_id,
        tool_result=tool_result,
        timestamp=timestamp,
    )


def _message_to_dto(msg: ModelMessage) -> MessageOut:
    if isinstance(msg, ModelRequest):
        kind = "request"
    elif isinstance(msg, ModelResponse):
        kind = "response"
    else:
        kind = type(msg).__name__
    parts = [_part_to_dto(p) for p in getattr(msg, "parts", [])]
    return MessageOut(kind=kind, parts=parts)


def to_dto(messages: list[ModelMessage]) -> list[MessageOut]:
    """Convert pydantic-ai messages into stable API DTOs."""
    return [_message_to_dto(m) for m in messages]