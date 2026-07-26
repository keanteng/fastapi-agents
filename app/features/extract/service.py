from __future__ import annotations

from app.features.extract.agent import extract_agent
from app.features.extract.schemas import ExtractionResult


async def extract(text: str) -> tuple[ExtractionResult, dict[str, int]]:
    async with extract_agent:
        result = await extract_agent.run(text)
    usage = result.usage
    return result.output, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "requests": usage.requests,
    }
