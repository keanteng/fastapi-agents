from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.capabilities.thinking import Thinking

from app.agents.definitions import AgentDefinition
from app.agents.models.extraction import ExtractionResult
from app.agents.tools import tool_adapter
from app.core.config import settings
from app.core.model import get_model
from app.core.prompts import render

_CAPABILITY_FACTORIES: dict[str, Callable[[], Any]] = {
    "thinking": Thinking,
}

_STRUCTURED_MODELS: dict[str, type[Any]] = {
    "ExtractionResult": ExtractionResult,
}


def resolve_output_model(schema: dict[str, Any] | None) -> Any:
    """Map an agent spec's ``output_schema`` to a pydantic output model."""
    if schema is None:
        return str
    title = schema.get("title")
    model = _STRUCTURED_MODELS.get(title)  # type: ignore[arg-type]
    if model is None:
        raise ValueError(
            f"no pydantic model registered for output schema title {title!r}"
        )
    return model


def resolve_capabilities(
    definition: AgentDefinition, hints: list[str] | None
) -> list[Any]:
    """Resolve requested capability names against the spec's declared set."""
    declared = set(definition.capabilities)
    names = set(hints) & declared if hints is not None else declared
    return [
        _CAPABILITY_FACTORIES[name]()
        for name in sorted(names)
        if name in _CAPABILITY_FACTORIES
    ]


def build_agent(
    definition: AgentDefinition,
    tools: dict[str, Callable],
    capabilities: list[str] | None = None,
    model: Any | None = None,
) -> Agent[None, Any]:
    """Build a pydantic-ai ``Agent`` from a declarative spec."""
    resolved_model = model or get_model()
    registered_tools = [tool_adapter(fn, name) for name, fn in tools.items()]
    output_type = resolve_output_model(definition.output_schema)
    return Agent(
        resolved_model,
        instructions=lambda _: render(definition.instructions),
        output_type=output_type,
        tools=registered_tools,
        capabilities=resolve_capabilities(definition, capabilities),
        name=definition.name,
        retries=settings.model_retries,
    )
