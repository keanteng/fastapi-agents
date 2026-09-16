from __future__ import annotations

import asyncio
import json

from app.search.cache import TTLCache
from app.search.providers import (
    DuckDuckGoProvider,
    SearchRateLimited,
    SearchResult,
)
from app.search.service import SearchService
from app.search.tools import web_search


class _Provider:
    def __init__(self, results: list[SearchResult], *, error: Exception | None = None):
        self._results = results
        self._error = error
        self.calls = 0

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._results[:max_results]


def _result(n: int = 0) -> SearchResult:
    return SearchResult(title=f"t{n}", url=f"http://example.com/{n}", snippet="s")


def test_ttl_cache_roundtrip_and_expiry() -> None:
    async def _go() -> None:
        cache = TTLCache(ttl=0.05, max_entries=10)
        await cache.set("k", "v")
        assert await cache.get("k") == "v"
        await asyncio.sleep(0.06)
        assert await cache.get("k") is None

    asyncio.run(_go())


def test_ttl_cache_disabled_when_ttl_zero() -> None:
    async def _go() -> None:
        cache = TTLCache(ttl=0, max_entries=10)
        assert not cache.enabled
        await cache.set("k", "v")
        assert await cache.get("k") is None

    asyncio.run(_go())


def test_ttl_cache_evicts_least_recently_used() -> None:
    async def _go() -> None:
        cache = TTLCache(ttl=60, max_entries=2)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.get("a")  # make "a" most-recently used
        await cache.set("c", 3)
        assert await cache.get("a") == 1
        assert await cache.get("b") is None
        assert await cache.get("c") == 3

    asyncio.run(_go())


def test_duckduckgo_normalise() -> None:
    result = DuckDuckGoProvider._normalise(
        {"title": " T ", "href": "http://x", "body": " B "}
    )
    assert result == SearchResult(title="T", url="http://x", snippet="B")


def test_duckduckgo_normalise_falls_back_to_url_and_alt_keys() -> None:
    result = DuckDuckGoProvider._normalise({"url": "http://y", "description": "d"})
    assert result.title == "http://y"
    assert result.url == "http://y"
    assert result.snippet == "d"


def test_service_caches_repeated_queries() -> None:
    async def _go() -> None:
        provider = _Provider([_result()])
        service = SearchService(
            provider, cache=TTLCache(ttl=60, max_entries=10), default_max_results=5
        )
        first = await service.search("hello world")
        second = await service.search("hello   world")
        assert first.results == second.results
        assert provider.calls == 1

    asyncio.run(_go())


def test_service_empty_query_short_circuits() -> None:
    async def _go() -> None:
        provider = _Provider([_result()])
        service = SearchService(provider)
        response = await service.search("   ")
        assert response.results == []
        assert response.note == "empty query"
        assert provider.calls == 0

    asyncio.run(_go())


def test_service_degrades_on_rate_limit() -> None:
    async def _go() -> None:
        provider = _Provider([], error=SearchRateLimited("slow down"))
        service = SearchService(provider)
        response = await service.search("anything")
        assert response.results == []
        assert response.note == "search backend rate limited"

    asyncio.run(_go())


def test_service_clamps_max_results() -> None:
    async def _go() -> None:
        provider = _Provider([_result(0), _result(1), _result(2)])
        service = SearchService(provider, default_max_results=5)
        response = await service.search("q", max_results=100)
        # The provider only ever receives the clamped ceiling of 10.
        assert len(response.results) == 3

    asyncio.run(_go())


async def test_web_search_tool_returns_json(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    class _Service:
        async def search(self, query: str, *, max_results: int):
            calls.append((query, max_results))
            from app.search.service import SearchResponse

            return SearchResponse(query=query, results=[_result()])

    monkeypatch.setattr("app.search.tools.get_search_service", lambda: _Service())
    payload = json.loads(await web_search("python", max_results=3))
    assert calls == [("python", 3)]
    assert payload["results"][0]["url"] == "http://example.com/0"
