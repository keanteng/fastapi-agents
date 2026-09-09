from __future__ import annotations

import json
from typing import Any, cast

from app.mcp_server import app as mcp_app


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # FastMCP's call_tool actually returns ``(content, structured_content)``
    # despite its declared ``Sequence[ContentBlock] | dict`` return type.
    result = await mcp_app.call_tool(name, arguments)
    _content, structured = cast(tuple[Any, dict[str, Any]], result)
    return structured


async def test_tools_listed() -> None:
    tools = await mcp_app.list_tools()
    names = {tool.name for tool in tools}
    assert {"calculator", "fetch", "current_time", "dispatch_skill"} <= names


async def test_call_calculator() -> None:
    structured = await _call("calculator", {"expression": "1+1"})
    assert structured["result"] == "2"


async def test_call_fetch_uses_stub() -> None:
    # The autouse conftest patch keeps http_fetch off the network.
    structured = await _call("fetch", {"url": "http://example.com"})
    assert structured["result"] == "stub-body"


async def test_call_current_time() -> None:
    structured = await _call("current_time", {})
    assert structured["result"].endswith("Z") or "+00:00" in structured["result"]


async def test_prompts_listed() -> None:
    prompts = await mcp_app.list_prompts()
    names = {prompt.name for prompt in prompts}
    assert {"summarizer", "translator", "code_reviewer"} <= names


async def test_catalog_resource_lists_agents() -> None:
    contents = list(await mcp_app.read_resource("agents://catalog"))
    payload = json.loads(contents[0].content)
    agent_names = {agent["name"] for agent in payload["agents"]}
    assert agent_names == {"generalist"}
