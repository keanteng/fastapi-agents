from __future__ import annotations

from pydantic_ai import Agent

from app.core.model import get_model
from app.core.prompts import render

chat_agent: Agent[None, str] = Agent(
    get_model(),
    instructions=lambda _: render("chat"),
    output_type=str,
)