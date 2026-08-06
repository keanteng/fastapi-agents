from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentDefinition(BaseModel):
    """Declarative agent spec loaded from ``app/agents/specs/*.yaml``."""

    name: str
    description: str
    instructions: str = Field(..., description="Key into app/core/prompts.yml.")
    model: str | None = None  # null -> settings.deepseek_model
    output_type: Literal["string", "structured_output"] = "string"
    output_schema: dict[str, Any] | None = None  # JSON schema when structured_output
    capabilities: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    uses_memory: bool = False
    default_max_steps: int = 8
