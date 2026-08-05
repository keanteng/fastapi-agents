from __future__ import annotations

import ast
import functools
import inspect
import operator
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic_ai import ModelRetry
from pydantic_ai.tools import Tool

# --------------------------------------------------------------------------- #
# Safe arithmetic evaluator
# --------------------------------------------------------------------------- #

_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS: dict[type, Callable[[Any], Any]] = {
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


def calculator(expression: str) -> str:
    """Evaluate a numeric expression and return the result as a string."""
    return str(safe_eval(expression))


def current_time() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Shared tool registry + pydantic-ai adapter (single source of truth)
# --------------------------------------------------------------------------- #


def shared_tools() -> dict[str, Callable]:
    """The shared tool callables by public name (single source of truth)."""
    return {
        "calculator": calculator,
        "fetch": http_fetch,
        "current_time": current_time,
    }


def tool_adapter(fn: Callable, name: str) -> Tool:
    """Wrap a plain shared callable as a pydantic-ai ``Tool``.

    Plain callables raise ordinary exceptions; this adapter converts them into
    ``ModelRetry`` so the model can self-correct (pydantic-ai idiom).
    """
    is_async = inspect.iscoroutinefunction(fn)

    @functools.wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            if is_async:
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)
        except ModelRetry:
            raise
        except Exception as exc:  # noqa: BLE001 - surface to the model via retry
            raise ModelRetry(f"{name} failed: {exc}") from exc

    return Tool(wrapped, name=name)
