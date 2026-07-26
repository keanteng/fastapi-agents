from __future__ import annotations

from pydantic_ai import Agent

from app.core.model import get_model
from app.core.prompts import render

memory_agent: Agent[None, str] = Agent(
    get_model(),
    instructions=lambda ctx: render(
        "features/memory/templates/system.jinja",
        conversation_id=ctx.conversation_id or "",
    ),
    output_type=str,
)
