from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import BaseModel, Field

from app.core import metrics
from app.core.config import settings
from app.search.cache import TTLCache
from app.search.providers import (
    DuckDuckGoProvider,
    SearchError,
    SearchProvider,
    SearchRateLimited,
    SearchResult,
    SearchTimeout,
)

logger = logging.getLogger(__name__)

MAX_RESULTS_CEILING = 10


class SearchResponse(BaseModel):
    """The result of one ``web_search`` call, always JSON-serialisable."""

    query: str
    results: list[SearchResult] = Field(default_factory=list)
    note: str | None = None


class SearchService:
    """Provider + TTL cache, with graceful degradation on backend failures."""

    def __init__(
        self,
        provider: SearchProvider,
        *,
        cache: TTLCache | None = None,
        default_max_results: int = 5,
    ) -> None:
        self._provider = provider
        self._cache = cache or TTLCache(ttl=0, max_entries=0)
        self._default_max_results = default_max_results

    async def search(
        self, query: str, *, max_results: int | None = None
    ) -> SearchResponse:
        cleaned = " ".join(query.split())
        if not cleaned:
            return SearchResponse(query="", note="empty query")

        limit = max_results or self._default_max_results
        limit = max(1, min(limit, MAX_RESULTS_CEILING))
        cache_key = f"{cleaned.casefold()}::{limit}"

        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            results = await self._provider.search(cleaned, max_results=limit)
        except SearchRateLimited:
            logger.warning("web search rate limited for query %r", cleaned)
            metrics.observe_search("rate_limited")
            return SearchResponse(query=cleaned, note="search backend rate limited")
        except SearchTimeout:
            logger.warning("web search timed out for query %r", cleaned)
            metrics.observe_search("timeout")
            return SearchResponse(query=cleaned, note="search backend timed out")
        except SearchError as exc:
            logger.warning("web search failed for query %r: %s", cleaned, exc)
            metrics.observe_search("error")
            return SearchResponse(query=cleaned, note="search backend unavailable")
        except Exception:  # noqa: BLE001 - never fail the agent run on search
            logger.exception("unexpected web search failure for query %r", cleaned)
            metrics.observe_search("error")
            return SearchResponse(query=cleaned, note="search backend unavailable")

        response = SearchResponse(query=cleaned, results=results)
        await self._cache.set(cache_key, response)
        metrics.observe_search("success")
        return response


@lru_cache(maxsize=1)
def get_search_service() -> SearchService:
    """Return the process-wide search service built from settings."""
    provider: SearchProvider
    if settings.search_provider == "duckduckgo":
        provider = DuckDuckGoProvider(
            timeout=settings.search_timeout_seconds,
            region=settings.search_region,
        )
    else:
        provider = _NullProvider()
    return SearchService(
        provider,
        cache=TTLCache(
            ttl=settings.search_cache_ttl_seconds,
            max_entries=settings.search_cache_max_entries,
        ),
        default_max_results=settings.search_max_results,
    )


class _NullProvider:
    """Provider used when search is disabled; always yields no results."""

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        return []
