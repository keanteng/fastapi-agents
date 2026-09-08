from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets import FunctionToolset

import app.agents.tools as tools_module
from app.agents.tools import (
    calculator,
    current_time,
    safe_eval,
    tool_adapter,
)


def test_safe_eval_basic() -> None:
    assert safe_eval("(1+2)*3") == 9


def test_safe_eval_rejects_imports_and_names() -> None:
    with pytest.raises(ValueError):
        safe_eval("__import__('os')")
    with pytest.raises(ValueError):
        safe_eval("os.system('ls')")


def test_calculator() -> None:
    assert calculator("1+1") == "2"


def test_current_time_is_iso_utc() -> None:
    value = current_time()
    assert value.endswith("Z") or "+00:00" in value
    from datetime import datetime

    datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_http_fetch_is_stubbed() -> None:
    # The autouse conftest patch replaces http_fetch with a stub, so this
    # never touches the network.
    assert asyncio.run(tools_module.http_fetch("http://example.com")) == "stub-body"


async def test_tool_adapter_converts_errors_to_model_retry() -> None:
    def _boom(x: str) -> str:
        raise ValueError("nope")

    agent = Agent(
        TestModel(call_tools=["boom"], custom_output_text="x"),
        tools=[tool_adapter(_boom, "boom")],
        output_type=str,
    )
    tool = cast(FunctionToolset, agent.toolsets[0]).tools["boom"]
    function = cast(Callable[..., Awaitable[Any]], tool.function)
    with pytest.raises(ModelRetry):
        await function(x="hi")
