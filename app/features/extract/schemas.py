"""Schemas for the extract slice.

``ExtractionResult`` doubles as the agent's structured ``output_type``: the
model is forced to fill it, and pydantic-ai validates + retries on failure.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Entity(BaseModel):
    name: str = Field(..., description="The entity's surface form.")
    type: str = Field(..., description="PER, ORG, LOC, DATE, MISC.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    """Structured output the agent must return."""

    entities: list[Entity] = Field(default_factory=list)
    language: str | None = Field(
        default=None, description="Detected dominant language code (e.g. 'en')."
    )
    summary: str = Field(default="", description="One-sentence summary of the input.")


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length=1)


class ExtractResponse(BaseModel):
    result: ExtractionResult
    usage: dict[str, int] = Field(default_factory=dict)