from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from pydantic_ai import Agent

from app.features.skills.skills.skills import SKILL_FACTORIES


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    factory: Callable[[], Agent[None, str]]


def build_registry() -> dict[str, Skill]:
    return {
        name: Skill(name=name, description=desc, factory=factory)
        for name, (desc, factory) in SKILL_FACTORIES.items()
    }


REGISTRY: Final[dict[str, Skill]] = build_registry()


def available_skills() -> dict[str, str]:
    return {name: skill.description for name, skill in REGISTRY.items()}


def get_skill(name: str) -> Skill | None:
    skill = REGISTRY.get(name)
    if skill is None:
        # case-insensitive fallback
        lower = name.lower()
        for k, v in REGISTRY.items():
            if k.lower() == lower:
                return v
    return skill
