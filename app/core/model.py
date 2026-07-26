from __future__ import annotations

from functools import lru_cache

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from app.core.config import settings


@lru_cache(maxsize=1)
def get_model() -> OpenAIChatModel:
    return OpenAIChatModel(
        settings.deepseek_model,
        provider=DeepSeekProvider(api_key=settings.deepseek_api_key),
    )
