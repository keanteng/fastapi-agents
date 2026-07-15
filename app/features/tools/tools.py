"""Function tools exposed to the tools agent.

Demonstrates ``@agent.tool`` (instance method receiving ``RunContext``) and
``@agent.tool_plain`` (no deps) forms.
"""

from __future__ import annotations

import ast
import operator
from datetime import datetime, timezone
from typing import Annotated

import httpx
from pydantic_ai import RunContext

# --------------------------------------------------------------------------- #
# Safe arithmetic evaluator
# --------------------------------------------------------------------------- #

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def safe_eval(expression: str) -> float | int:
    tree = ast.parse(expression, mode="eval")
    return _eval(tree)


async def http_fetch(url: str, *, timeout: float = 10.0) -> str:
    """Fetch up to 4096 chars of text from an HTTP URL."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)
        response.raise_for_status()
    return response.text[:4096]


# --------------------------------------------------------------------------- #
# Pydantic AI tool registrations
# --------------------------------------------------------------------------- #

# NOTE: the agent is imported lazily inside ``register_tools`` to avoid an
# import cycle (the agent module imports this module).



def register_tools(agent) -> None:  # type: ignore[no-untyped-def]
    """Attach function tools to ``agent``."""

    @agent.tool_plain
    def calculator(expression: Annotated[str, "A numeric expression, e.g. '(1+2)*3'"]) -> str:
        """Evaluate a numeric expression and return the result."""
        try:
            value = safe_eval(expression)
        except Exception as exc:  # noqa: BLE001 - surface to the model via retry message
            from pydantic_ai import ModelRetry
            raise ModelRetry(f"could not evaluate {expression!r}: {exc}") from exc
        return str(value)

    @agent.tool
    async def fetch(
        ctx: RunContext[None],
        url: Annotated[str, "Absolute http(s) URL to fetch"],
    ) -> str:
        """Fetch the raw text at ``url`` (truncated to 4 KiB)."""
        try:
            return await http_fetch(url)
        except Exception as exc:  # noqa: BLE001
            from pydantic_ai import ModelRetry
            raise ModelRetry(f"fetch failed for {url}: {exc}") from exc

    @agent.tool_plain
    def current_time() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()