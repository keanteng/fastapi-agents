"""DeepSeek model access.

DeepSeek speaks the OpenAI Chat Completions wire format, so it works with
``OpenAIChatModel`` + ``DeepSeekProvider``.

A shared model instance is built once (``get_model``). The API key defaults to
a harmless placeholder so the app imports without credentials present; real
calls require a valid ``DEEPSEEK_API_KEY`` set in the environment. Tests swap
the model out for pydantic-ai's ``TestModel`` (see ``tests/conftest.py``).
"""

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