from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage

from app.features.chat.agent import chat_agent


async def run_chat(user_prompt: str) -> tuple[str, list[ModelMessage], dict[str, int]]:
    """Run a single-turn chat and return (output, new_messages, usage)."""
    async with chat_agent:
        result = await chat_agent.run(user_prompt)
    usage = result.usage
    return (
        result.output,
        result.new_messages(),
        {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "requests": usage.requests,
        },
    )


async def stream_chat(user_prompt: str) -> AsyncIterator[str]:
    """Yield text deltas from a streamed chat run."""
    async with chat_agent:
        async with chat_agent.run_stream(user_prompt) as result:
            async for chunk in result.stream_text():
                yield chunk
