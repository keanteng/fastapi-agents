from __future__ import annotations

from pydantic import BaseModel, Field

# DTOs now live in app.agents.memory.schemas; the legacy router aliases them
# until the features slice is deleted (Task 10).
from app.agents.memory.schemas import MessageOut  # noqa: F401


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
    system_prompt: str | None = Field(
        default=None,
        description="Optional prompt task key override "
        "(see app/core/prompts.yml; defaults to 'memory').",
    )


class MemoryChatResponse(BaseModel):
    conversation_id: str
    output: str
    usage: dict[str, int] = Field(default_factory=dict)


class ConversationCreateResponse(BaseModel):
    conversation_id: str = Field(
        ..., description="Server-generated id for a newly provisioned conversation."
    )
