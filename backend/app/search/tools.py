from __future__ import annotations

from collections.abc import Callable

from app.search.service import get_search_service


async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for ``query`` and return JSON: {query, results:[{title,url,snippet}], note}."""
    service = get_search_service()
    response = await service.search(query, max_results=max_results)
    return response.model_dump_json()


def make_search_tools() -> dict[str, Callable]:
    """The shared search callables registered on the agents."""
    return {"web_search": web_search}
