from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from yaml import safe_load

from app.agents import build
from app.agents.definitions import AgentDefinition
from app.agents.delegation import make_delegate_tools
from app.agents.skills import dispatch_skill

SPECS_DIR = Path(__file__).resolve().parent / "specs"


class AgentRegistry:
    """Holds declarative agent definitions and the shared tool callables."""

    def __init__(self, definitions: dict[str, AgentDefinition]) -> None:
        self.definitions = definitions
        self.tools: dict[str, Callable] = {}
        self._init_tools()

    def _init_tools(self) -> None:
        from app.agents import tools as tools_module

        self.tools = {
            "calculator": tools_module.calculator,
            "fetch": tools_module.http_fetch,
            "current_time": tools_module.current_time,
            "dispatch_skill": dispatch_skill,
        }
        self.tools.update(make_delegate_tools(self.build_agent))

    def build_agent(
        self,
        name: str,
        tools: list[str] | None = None,
        capabilities: list[str] | None = None,
        model: Any | None = None,
    ) -> Agent[None, Any]:
        """Resolve a spec and build a pydantic-ai ``Agent`` for one run."""
        definition = self.definitions.get(name)
        if definition is None:
            raise KeyError(name)
        requested = tools if tools is not None else definition.tools
        effective_names = [n for n in requested if n in self.tools]
        resolved_tools = {n: self.tools[n] for n in effective_names}
        return build.build_agent(definition, resolved_tools, capabilities, model)


def load_agent_registry() -> AgentRegistry:
    """Load every ``app/agents/specs/*.yaml`` file into an ``AgentRegistry``."""
    definitions: dict[str, AgentDefinition] = {}
    for path in sorted(SPECS_DIR.glob("*.yaml")):
        data = safe_load(path.read_text(encoding="utf-8"))
        definition = AgentDefinition.model_validate(data)
        definitions[definition.name] = definition
    return AgentRegistry(definitions)
