from __future__ import annotations

import pytest

from app.agents.skills import available_skills, dispatch_skill, get_skill
from app.core.prompts import get_engine


def test_available_skills() -> None:
    assert set(available_skills()) == {"summarizer", "translator", "code_reviewer"}


def test_get_skill_case_insensitive() -> None:
    skill = get_skill("Summarizer")
    assert skill is not None
    assert skill[0] == "Summarise a piece of text into a few key bullet points."


def test_skill_prompt_templates_render() -> None:
    engine = get_engine()
    assert "summar" in engine.render("skill_summarizer").lower()
    assert "translator" in engine.render("skill_translator").lower()
    assert "review" in engine.render("skill_code_reviewer").lower()


async def test_dispatch_skill_runs_subagent() -> None:
    # The autouse conftest patch points skills.get_model at TestModel, so
    # dispatch_skill returns the canned "skill-output" text.
    output = await dispatch_skill("summarizer", "Hello world. This is a test.")
    assert output == "skill-output"


async def test_dispatch_skill_unknown_raises() -> None:
    with pytest.raises(ValueError):
        await dispatch_skill("does-not-exist", "text")
