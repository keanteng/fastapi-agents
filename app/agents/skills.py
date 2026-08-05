from __future__ import annotations

from collections.abc import Callable

from pydantic_ai import Agent

from app.core.model import get_model
from app.core.prompts import render


def _skill_agent(prompt_task: str) -> Agent[None, str]:
    return Agent(
        get_model(),
        instructions=lambda _: render(prompt_task),
        output_type=str,
    )


def summarizer_skill() -> Agent[None, str]:
    return _skill_agent("skill_summarizer")


def translator_skill() -> Agent[None, str]:
    return _skill_agent("skill_translator")


def code_reviewer_skill() -> Agent[None, str]:
    return _skill_agent("skill_code_reviewer")


SKILL_FACTORIES: dict[str, tuple[str, Callable[[], Agent[None, str]]]] = {
    "summarizer": (
        "Summarise a piece of text into a few key bullet points.",
        summarizer_skill,
    ),
    "translator": (
        "Translate text into a target language (default: French).",
        translator_skill,
    ),
    "code_reviewer": (
        "Review a small code snippet and surface issues.",
        code_reviewer_skill,
    ),
}


def available_skills() -> dict[str, str]:
    return {name: desc for name, (desc, _factory) in SKILL_FACTORIES.items()}


def get_skill(name: str) -> tuple[str, Callable[[], Agent[None, str]]] | None:
    if name in SKILL_FACTORIES:
        return SKILL_FACTORIES[name]
    lower = name.lower()
    for key, value in SKILL_FACTORIES.items():
        if key.lower() == lower:
            return value
    return None


async def dispatch_skill(skill_name: str, input_text: str) -> str:
    """Run the named skill sub-agent on ``input_text`` and return its output.

    Shared callable for the run API (via ``tool_adapter``) and the MCP server
    (via ``@mcp.tool``). Raises ``ValueError`` for unknown skills.
    """
    skill = get_skill(skill_name)
    if skill is None:
        raise ValueError(
            f"unknown skill {skill_name!r}. Available: {sorted(available_skills())}"
        )
    _desc, factory = skill
    agent = factory()
    async with agent:
        result = await agent.run(input_text)
    return result.output
