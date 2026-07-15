"""Tools agent: chat agent + function tools."""

from __future__ import annotations

from pydantic_ai import Agent

from app.core.model import get_model
from app.core.prompts import render
from app.features.tools.tools import register_tools

tools_agent: Agent[None, str] = Agent(
    get_model(),
    instructions=lambda _: render("features/tools/templates/system.jinja"),
    output_type=str,
)
register_tools(tools_agent)