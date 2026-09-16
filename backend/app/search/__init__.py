"""Web search slice.

A small, provider-agnostic search layer the generalist agent can call:

- ``providers`` adapts concrete backends (DuckDuckGo by default) to one result
  shape and normalises their failures into a handful of ``SearchError`` types.
- ``cache`` is a bounded TTL cache that keeps repeated queries (the main cause
  of free-tier rate limits) off the network.
- ``service`` composes provider + cache and degrades gracefully: a backend
  failure yields an empty result set instead of aborting the agent run.
"""

from app.search.providers import (
    DuckDuckGoProvider,
    SearchError,
    SearchProvider,
    SearchRateLimited,
    SearchResult,
    SearchTimeout,
)
from app.search.service import SearchService, get_search_service

__all__ = [
    "DuckDuckGoProvider",
    "SearchError",
    "SearchProvider",
    "SearchRateLimited",
    "SearchResult",
    "SearchService",
    "SearchTimeout",
    "get_search_service",
]
