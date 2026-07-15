"""Multi-step task orchestrator agent."""

from __future__ import annotations

from pydantic_ai import Agent, UsageLimits

from app.core.model import get_model
from app.core.prompts import render
from app.features.tasks.executor import register_task_tools

tasks_agent: Agent[None, str] = Agent(
    get_model(),
    instructions=lambda _: render("features/tasks/templates/orchestrator.jinja"),
    output_type=str,
)
register_task_tools(tasks_agent)

_default_limits = UsageLimits(request_limit=12, tool_calls_limit=8)
"""Sensible bound preventing runaway multi-step loops."""


def run_limits(max_steps: int) -> UsageLimits:
    # 1 plan + ~2 requests per step + slack
    return UsageLimits(
        request_limit=max(2, max_steps * 3),
        tool_calls_limit=max(1, max_steps),
    )