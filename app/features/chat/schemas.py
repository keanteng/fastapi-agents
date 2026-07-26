from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_prompt: str = Field(..., min_length=1, description="The user's message.")
    conversation_id: str | None = Field(
        default=None,
        description="Optional id; when supplied the slice can store messages "
        "for replay. Not required for stateless chat.",
    )


class ChatResponse(BaseModel):
    output: str
    conversation_id: str | None = None
    usage: dict[str, int] = Field(
        default_factory=dict,
        description="Token/request usage for the run.",
    )
