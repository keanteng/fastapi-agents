"""Chat agent.

Stateless chat agent backed by DeepSeek. The system prompt is rendered from a
Jinja template so prompt-engineering lives in files, not source.
"""

from __future__ import annotations

from pydantic_ai import Agent

from app.core.model import get_model
from app.core.prompts import render

chat_agent: Agent[None, str] = Agent(
    get_model(),
    instructions=lambda _: render("features/chat/templates/system.jinja"),
    output_type=str,
)
"""Shared chat agent used by both the chat and memory slices."""