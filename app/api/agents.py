from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agents.definitions import AgentDefinition
from app.api.errors import AppError

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


class AgentSpecOut(BaseModel):
    name: str
    description: str
    instructions_key: str
    output_type: Literal["string", "structured_output"]
    output_schema: dict[str, Any] | None = None
    tools: list[str]
    capabilities: list[str]
    uses_memory: bool
    default_max_steps: int

    @classmethod
    def from_definition(cls, definition: AgentDefinition) -> "AgentSpecOut":
        return cls(
            name=definition.name,
            description=definition.description,
            instructions_key=definition.instructions,
            output_type=definition.output_type,
            output_schema=definition.output_schema,
            tools=list(definition.tools),
            capabilities=list(definition.capabilities),
            uses_memory=definition.uses_memory,
            default_max_steps=definition.default_max_steps,
        )


@router.get("", response_model=list[AgentSpecOut])
async def list_agents(request: Request) -> list[AgentSpecOut]:
    registry = request.app.state.container.agents
    return [AgentSpecOut.from_definition(d) for d in registry.definitions.values()]


@router.get("/{name}", response_model=AgentSpecOut)
async def get_agent(name: str, request: Request) -> AgentSpecOut:
    registry = request.app.state.container.agents
    definition = registry.definitions.get(name)
    if definition is None:
        raise AppError(404, "agent_not_found", f"agent {name!r} does not exist")
    return AgentSpecOut.from_definition(definition)
