from __future__ import annotations

from typing import Annotated

from pydantic_ai import Agent, ModelRetry

from app.core.model import get_model
from app.core.prompts import render
from app.features.skills.registry import Skill, available_skills, get_skill

skills_agent: Agent[None, str] = Agent(
    get_model(),
    instructions=lambda _: render(
        "skills_orchestrator",
        skills={name: (desc, None) for name, desc in available_skills().items()},
    ),
    output_type=str,
)


@skills_agent.tool_plain
async def dispatch_skill(
    skill_name: Annotated[str, "Name of the skill to invoke, e.g. 'summarizer'"],
    input_text: Annotated[str, "The text to pass to that skill"],
) -> str:
    """Run the named skill on ``input_text`` and return its output."""
    skill: Skill | None = get_skill(skill_name)
    if skill is None:
        raise ModelRetry(
            f"unknown skill {skill_name!r}. Available: {sorted(available_skills())}"
        )
    agent = skill.factory()
    async with agent:
        result = await agent.run(input_text)
    return result.output
