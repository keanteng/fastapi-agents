"""Available skills for the skills slice.

Each skill is a ``Toolset`` of one or more tools plus a short description the
orchestrator uses to decide which skill to dispatch.
"""

from __future__ import annotations

from pydantic_ai import Agent

from app.core.model import get_model
from app.core.prompts import render


def summarizer_skill() -> Agent[None, str]:
    agent: Agent[None, str] = Agent(
        get_model(),
        instructions=lambda _: render("features/skills/templates/summarizer.jinja"),
        output_type=str,
    )
    return agent


def translator_skill() -> Agent[None, str]:
    agent: Agent[None, str] = Agent(
        get_model(),
        instructions=lambda _: render("features/skills/templates/translator.jinja"),
        output_type=str,
    )
    return agent


def code_reviewer_skill() -> Agent[None, str]:
    agent: Agent[None, str] = Agent(
        get_model(),
        instructions=lambda _: render("features/skills/templates/code_reviewer.jinja"),
        output_type=str,
    )
    return agent


SKILL_FACTORIES = {
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
