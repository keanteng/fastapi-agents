from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from pydantic_ai.models.openai import OpenAIChatModel

from app.core.config import Settings
from app.core.model import get_model
from app.core.prompts import PromptEngine


@dataclass
class AppContainer:
    """Root container holding process-wide singletons."""

    config: Settings
    model: OpenAIChatModel
    prompts: PromptEngine


_container: AppContainer | None = None


def build_container(config: Settings | None = None) -> AppContainer:
    """Construct and cache every application-scoped singleton."""
    global _container
    resolved = config or Settings()
    container = AppContainer(
        config=resolved,
        model=get_model(),
        prompts=PromptEngine(),
    )
    _container = container
    return container


def get_container() -> AppContainer:
    """Return the process-wide container, building it lazily if needed.

    The running server builds it explicitly in the lifespan; this lazy path
    covers scripts and tests that use the app outside a request lifecycle.
    """
    global _container
    if _container is None:
        build_container()
    assert _container is not None  # noqa: S101 -- for type checkers
    return _container


def get_container_from_request(request: Request) -> AppContainer:
    """FastAPI dependency yielding the container stored on ``app.state``."""
    return request.app.state.container


def close_container() -> None:
    """Drop the cached container (called on app shutdown)."""
    global _container
    _container = None
