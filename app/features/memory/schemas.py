from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PartOut(BaseModel):
    kind: str = Field(
        ..., description="pydantic-ai part_kind, e.g. user-prompt/tool-call."
    )
    role: str = Field(
        ..., description="Stable role: user|assistant|system|tool|unknown."
    )
    content: str | None = Field(
        default=None, description="Text content for text-like parts."
    )
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_call_id: str | None = None
    tool_result: Any | None = None
    timestamp: datetime | None = None


class MessageOut(BaseModel):
    kind: str = Field(
        ..., description="request|response (mirrors ModelRequest/ModelResponse)."
    )
    parts: list[PartOut] = Field(default_factory=list)


class AppendMessages(BaseModel):
    user_prompt: str = Field(
        ..., min_length=1, description="User's utterance to store."
    )


class MemoryListResponse(BaseModel):
    conversation_id: str
    messages: list[MessageOut] = Field(
        default_factory=list,
        description="Message history as a list of stable DTOs.",
    )


class MemoryAppendResponse(BaseModel):
    conversation_id: str
    messages_before: int
    messages_after: int


class MemoryChatRequest(BaseModel):
    user_prompt: str = Field(..., min_length=1)
    system_prompt_template: str | None = Field(
        default=None,
        description="Optional Jinja template path override "
        "(defaults to features/memory/templates/system.jinja).",
    )


class MemoryChatResponse(BaseModel):
    conversation_id: str
    output: str
    usage: dict[str, int] = Field(default_factory=dict)


class ConversationCreateResponse(BaseModel):
    conversation_id: str = Field(
        ..., description="Server-generated id for a newly provisioned conversation."
    )
