from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from app.core.config import settings


def _build_fallback_model() -> Any | None:
    """Build the optional OpenAI-compatible fallback model, if configured."""
    name = (settings.model_fallback or "").strip()
    if not name:
        return None
    from pydantic_ai.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        base_url=settings.model_fallback_base_url or None,
        api_key=settings.model_fallback_api_key or "stub",
    )
    return OpenAIChatModel(name, provider=provider)


@lru_cache(maxsize=1)
def get_model() -> Any:
    primary = OpenAIChatModel(
        settings.deepseek_model,
        provider=DeepSeekProvider(api_key=settings.deepseek_api_key),
    )
    fallback = _build_fallback_model()
    if fallback is None:
        return primary
    from pydantic_ai.models.fallback import FallbackModel

    return FallbackModel(primary, fallback)
