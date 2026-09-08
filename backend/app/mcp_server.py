"""Standalone FastMCP (stdio) server exposing the shared tools, skill prompts,
and an ``agents://catalog`` resource.

Run with ``uv run python -m app.mcp_server``.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from app.agents import tools as tools_module
from app.agents.registry import load_agent_registry
from app.agents.skills import dispatch_skill
from app.core.prompts import get_engine

app = FastMCP("agents")

_registry = load_agent_registry()


@app.tool(name="calculator")
def _calculator(expression: str) -> str:
    """Evaluate a safe numeric expression."""
    return tools_module.calculator(expression)


@app.tool(name="fetch")
async def _fetch(url: str, timeout: float = 10.0) -> str:
    """Fetch up to 4 KiB of text from an HTTP URL."""
    return await tools_module.http_fetch(url, timeout=timeout)


@app.tool(name="current_time")
def _current_time() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return tools_module.current_time()


@app.tool(name="dispatch_skill")
async def _dispatch_skill(skill_name: str, input_text: str) -> str:
    """Run a registered skill (summarizer/translator/code_reviewer)."""
    return await dispatch_skill(skill_name, input_text)


@app.prompt(name="summarizer")
def _summarizer(text: str) -> str:
    """Summarise text into bullet points."""
    return get_engine().render("skill_summarizer") + "\n\nUser text:\n" + text


@app.prompt(name="translator")
def _translator(text: str, target_language: str = "French") -> str:
    """Translate text into a target language."""
    return (
        get_engine().render("skill_translator")
        + f"\n\nTarget language: {target_language}\n\nUser text:\n{text}"
    )


@app.prompt(name="code_reviewer")
def _code_reviewer(code: str) -> str:
    """Review a code snippet."""
    return get_engine().render("skill_code_reviewer") + "\n\nUser code:\n" + code


@app.resource("agents://catalog")
def _catalog() -> str:
    """JSON document listing every declarative agent spec."""
    specs = [
        {
            "name": definition.name,
            "description": definition.description,
            "tools": list(definition.tools),
            "capabilities": list(definition.capabilities),
            "uses_memory": definition.uses_memory,
            "default_max_steps": definition.default_max_steps,
            "output_type": definition.output_type,
            "output_schema": definition.output_schema,
        }
        for definition in _registry.definitions.values()
    ]
    return json.dumps({"agents": specs}, indent=2)


def main() -> None:
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
