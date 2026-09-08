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
