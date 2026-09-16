from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    """One normalised search hit."""

    title: str
    url: str
    snippet: str = ""


class SearchError(RuntimeError):
    """Base class for recoverable search-backend failures."""


class SearchRateLimited(SearchError):
    """The backend refused the query because of a rate limit / bot check."""


class SearchTimeout(SearchError):
    """The backend did not respond before the timeout."""


@runtime_checkable
class SearchProvider(Protocol):
    """A web-search backend that returns normalised results."""

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        """Return up to ``max_results`` hits for ``query``."""
        ...


class DuckDuckGoProvider:
    """DuckDuckGo metasearch backend (``ddgs``).

    ``ddgs`` is synchronous and fans out across several upstream engines
    internally, so each call is offloaded to a worker thread.
    """

    def __init__(self, *, timeout: float = 10.0, region: str = "us-en") -> None:
        self._timeout = timeout
        self._region = region

    async def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        return await asyncio.to_thread(self._search_sync, query, max_results)

    def _search_sync(self, query: str, max_results: int) -> list[SearchResult]:
        from ddgs import DDGS
        from ddgs.exceptions import (
            DDGSException,
            RatelimitException,
            TimeoutException,
        )

        try:
            with DDGS(timeout=max(1, int(self._timeout))) as ddgs:
                rows: list[dict[str, Any]] = ddgs.text(
                    query,
                    region=self._region,
                    max_results=max_results,
                )
        except RatelimitException as exc:
            raise SearchRateLimited(str(exc) or "rate limited") from exc
        except TimeoutException as exc:
            raise SearchTimeout(str(exc) or "search timed out") from exc
        except DDGSException as exc:
            raise SearchError(str(exc) or "search backend error") from exc
        except Exception as exc:  # noqa: BLE001 - backend errors are recoverable
            raise SearchError(str(exc) or exc.__class__.__name__) from exc
        return [self._normalise(row) for row in rows or []]

    @staticmethod
    def _normalise(row: dict[str, Any]) -> SearchResult:
        title = str(row.get("title") or "").strip()
        url = str(row.get("href") or row.get("url") or "").strip()
        snippet = str(row.get("body") or row.get("description") or "").strip()
        if len(snippet) > 500:
            snippet = snippet[:500] + "…"
        return SearchResult(title=title or url, url=url, snippet=snippet)
