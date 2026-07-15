"""Tools service."""

from __future__ import annotations

from app.features.tools.agent import tools_agent


async def run_with_tools(user_prompt: str) -> tuple[str, dict[str, int]]:
    async with tools_agent:
        result = await tools_agent.run(user_prompt)
    usage = result.usage
    return result.output, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "requests": usage.requests,
    }