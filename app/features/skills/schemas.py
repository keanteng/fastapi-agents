"""Schemas for the skills slice."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillsRequest(BaseModel):
    user_prompt: str = Field(..., min_length=1)
    target_language: str | None = Field(
        default=None, description="Hint for the translator skill."
    )


class SkillsResponse(BaseModel):
    output: str
    skill: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)