"""Skills service."""

from __future__ import annotations

from app.features.skills.agent import skills_agent


async def orchestrate(user_prompt: str) -> tuple[str, dict[str, int]]:
    async with skills_agent:
        result = await skills_agent.run(user_prompt)
    usage = result.usage
    return result.output, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "requests": usage.requests,
    }