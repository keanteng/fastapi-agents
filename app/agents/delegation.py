from __future__ import annotations

from collections.abc import Callable

from app.agents.skills import dispatch_skill


def make_delegate_tools(build_agent: Callable) -> dict[str, Callable]:
    """Build the sub-agent delegation tools for the generalist agent.

    Each delegate tool runs a fresh generalist that has only the base tools
    (no delegation), so delegation cannot recurse.
    """

    async def delegate_chat(subtask: str) -> str:
        """Delegate a general conversational sub-task to a fresh generalist."""
        agent = build_agent(
            "generalist",
            tools=["calculator", "fetch", "current_time", "dispatch_skill"],
        )
        async with agent:
            result = await agent.run(subtask)
        return result.output

    async def delegate_tools(subtask: str) -> str:
        """Delegate a tool-needing sub-task to a fresh generalist."""
        agent = build_agent(
            "generalist",
            tools=["calculator", "fetch", "current_time", "dispatch_skill"],
        )
        async with agent:
            result = await agent.run(subtask)
        return result.output

    async def delegate_skill(skill_name: str, input_text: str) -> str:
        """Delegate a sub-task to a registered skill sub-agent."""
        return await dispatch_skill(skill_name, input_text)

    return {
        "delegate_chat": delegate_chat,
        "delegate_tools": delegate_tools,
        "delegate_skill": delegate_skill,
    }
