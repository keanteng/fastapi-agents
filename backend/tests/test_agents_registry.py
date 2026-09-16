from __future__ import annotations

import asyncio

import pytest
from pydantic_ai import Agent

from app.agents.definitions import AgentDefinition
from app.agents.registry import load_agent_registry


def test_registry_loads_generalist() -> None:
    registry = load_agent_registry()
    assert set(registry.definitions) == {"generalist"}
    assert registry.definitions["generalist"].uses_memory is True
    assert registry.definitions["generalist"].output_type == "string"


def test_registry_tools_include_shared_and_delegation() -> None:
    registry = load_agent_registry()
    assert set(registry.tools) == {
        "calculator",
        "fetch",
        "current_time",
        "web_search",
        "dispatch_skill",
        "delegate_chat",
        "delegate_tools",
        "delegate_skill",
        "document_text",
        "check_compliance",
        "extract_entities",
    }


def test_agent_definition_validates() -> None:
    definition = AgentDefinition.model_validate(
        {
            "name": "x",
            "description": "d",
            "instructions": "generalist",
            "output_type": "string",
            "tools": ["calculator"],
            "capabilities": ["thinking"],
            "uses_memory": True,
            "default_max_steps": 8,
        }
    )
    assert definition.name == "x"
    assert definition.capabilities == ["thinking"]


def test_build_agent_generalist_is_agent() -> None:
    registry = load_agent_registry()
    agent = registry.build_agent("generalist")
    assert isinstance(agent, Agent)


def test_build_agent_unknown_raises() -> None:
    registry = load_agent_registry()
    with pytest.raises(KeyError):
        registry.build_agent("nope")


def test_extraction_definition_output_model() -> None:
    from app.agents.build import resolve_output_model
    from app.agents.extraction import EXTRACTION_DEFINITION
    from app.agents.models.extraction import ExtractionResult

    assert resolve_output_model(EXTRACTION_DEFINITION.output_schema) is ExtractionResult


def test_build_agent_tool_filtering(agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    registry = load_agent_registry()
    agent_model(
        ScriptedTestModel(
            call_tools=["calculator"],
            tool_args={"calculator": {"expression": "1+1"}},
            custom_output_text="done",
        )
    )
    agent = registry.build_agent("generalist", tools=["calculator"])

    async def _run() -> str:
        async with agent:
            result = await agent.run("what is 1+1")
        return result.output

    assert asyncio.run(_run()) == "done"


def test_build_agent_ignores_unknown_capabilities(agent_model) -> None:
    from pydantic_ai.models.test import TestModel

    registry = load_agent_registry()
    agent_model(TestModel(custom_output_text="ok"))
    agent = registry.build_agent(
        "generalist", tools=[], capabilities=["does-not-exist"]
    )

    async def _run() -> str:
        async with agent:
            result = await agent.run("hi")
        return result.output

    assert asyncio.run(_run()) == "ok"


def test_build_agent_delegation_runs(agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    registry = load_agent_registry()
    agent_model(
        ScriptedTestModel(
            call_tools="all",
            tool_args={
                "calculator": {"expression": "1+1"},
                "fetch": {"url": "http://example.com"},
                "current_time": {},
                "dispatch_skill": {"skill_name": "summarizer", "input_text": "hello"},
                "delegate_chat": {"subtask": "chat sub"},
                "delegate_tools": {"subtask": "tool sub"},
                "delegate_skill": {"skill_name": "summarizer", "input_text": "hello"},
            },
            custom_output_text="outer-done",
        )
    )
    # Document tools need real uploads; keep them out of this delegation run.
    agent = registry.build_agent(
        "generalist",
        tools=[
            "calculator",
            "fetch",
            "current_time",
            "dispatch_skill",
            "delegate_chat",
            "delegate_tools",
            "delegate_skill",
        ],
    )

    async def _run() -> str:
        async with agent:
            result = await agent.run("do everything")
        return result.output

    assert asyncio.run(_run()) == "outer-done"
