"""Schemas for the tools slice."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolsRequest(BaseModel):
    user_prompt: str = Field(..., min_length=1)


class ToolsResponse(BaseModel):
    output: str
    usage: dict[str, int] = Field(default_factory=dict)