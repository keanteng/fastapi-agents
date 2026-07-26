from __future__ import annotations

from typing import Annotated

from pydantic_ai import ModelRetry, RunContext

from app.features.chat.agent import chat_agent
from app.features.skills.registry import available_skills, get_skill


async def _run_chat(prompt: str) -> str:
    async with chat_agent:
        result = await chat_agent.run(prompt)
    return result.output


async def _run_tools(prompt: str) -> str:
    # Imported here to avoid a circular import at module load time.
    from app.features.tools.agent import tools_agent

    async with tools_agent:
        result = await tools_agent.run(prompt)
    return result.output


async def _run_skill(skill_name: str, input_text: str) -> str:
    skill = get_skill(skill_name)
    if skill is None:
        raise ModelRetry(
            f"unknown skill {skill_name!r}. Available: {sorted(available_skills())}"
        )
    agent = skill.factory()
    async with agent:
        result = await agent.run(input_text)
    return result.output


def register_task_tools(agent) -> None:  # type: ignore[no-untyped-def]
    """Attach the sub-agent-delegating tools to ``agent``."""

    @agent.tool_plain
    async def delegate_chat(
        subtask: Annotated[str, "The sub-task description for the chat sub-agent"],
    ) -> str:
        """Delegate a general conversational sub-task to the chat sub-agent."""
        return await _run_chat(subtask)

    @agent.tool_plain
    async def delegate_tools(
        subtask: Annotated[
            str,
            "The sub-task requiring tools (math, time, url fetch) for the tools sub-agent",
        ],
    ) -> str:
        """Delegate a tool-needing sub-task to the tools sub-agent."""
        return await _run_tools(subtask)

    @agent.tool
    async def delegate_skill(
        _ctx: RunContext[None],
        skill_name: Annotated[str, "Name of the registered skill to invoke"],
        input_text: Annotated[str, "Input text for the chosen skill"],
    ) -> str:
        """Delegate a sub-task to a registered skill sub-agent."""
        return await _run_skill(skill_name, input_text)
