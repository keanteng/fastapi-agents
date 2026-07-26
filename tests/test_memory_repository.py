"""Repository-level tests using the shared in-memory SQLite engine.

These don't go through FastAPI; they exercise ``MemoryRepository`` directly to
verify JSON round-tripping and capacity/seq behaviour.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.features.memory.repository import MemoryRepository
from tests.conftest import _test_engine  # type: ignore[attr-defined]


def _user(prompt: str) -> ModelRequest:
    return ModelRequest(
        parts=[UserPromptPart(content=prompt, timestamp=datetime.now(UTC))]
    )


def _assistant(text: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=text)])


async def _repo() -> tuple[MemoryRepository, async_sessionmaker]:
    factory = async_sessionmaker(_test_engine, expire_on_commit=False)
    session = factory()
    repo = MemoryRepository(session)
    return repo, factory


@pytest.mark.asyncio
async def test_get_empty_returns_list() -> None:
    repo, _factory = await _repo()
    async with repo._session:  # type: ignore[attr-defined]
        assert await repo.get("nope") == []


@pytest.mark.asyncio
async def test_append_set_clear_roundtrip() -> None:
    repo, _factory = await _repo()
    async with repo._session:  # type: ignore[attr-defined]
        await repo.ensure("c1")
        await repo.append("c1", [_user("hello")])
        msgs = await repo.get("c1")
        assert len(msgs) == 1
        assert isinstance(msgs[0], ModelRequest)

        await repo.set("c1", [_user("a"), _assistant("b")])
        msgs = await repo.get("c1")
        assert len(msgs) == 2
        assert isinstance(msgs[0], ModelRequest)
        assert isinstance(msgs[1], ModelResponse)

        assert await repo.count("c1") == 2
        assert await repo.clear("c1") is True
        assert await repo.clear("c1") is False  # gone now


@pytest.mark.asyncio
async def test_capacity_caps_history() -> None:
    repo, _factory = await _repo()
    async with repo._session:  # type: ignore[attr-defined]
        await repo.ensure("c2")
        big = [_user(f"m{i}") for i in range(5)]
        capped = MemoryRepository(repo._session, capacity=2)  # type: ignore[attr-defined]
        await capped.append("c2", big)
        msgs = await capped.get("c2")
        assert len(msgs) == 2  # last two kept


@pytest.mark.asyncio
async def test_list_ids() -> None:
    repo, _factory = await _repo()
    async with repo._session:  # type: ignore[attr-defined]
        await repo.ensure("a")
        await repo.ensure("b")
        ids = await repo.list_ids()
        assert set(ids) >= {"a", "b"}
