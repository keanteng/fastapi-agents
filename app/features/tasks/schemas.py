"""Schemas for the tasks slice."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskStep(BaseModel):
    step: int
    tool: str
    summary: str
    result: str


class TasksRequest(BaseModel):
    goal: str = Field(..., min_length=1, description="The multi-step goal to perform.")
    max_steps: int = Field(default=5, ge=1, le=10)
    skill: str | None = Field(
        default="summarizer", description="Skill name passed to delegate_skill steps."
    )


class TasksResponse(BaseModel):
    output: str
    steps: list[TaskStep] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)