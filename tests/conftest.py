"""Test fixtures.

Every slice agent is swapped onto pydantic-ai's ``TestModel`` so the test suite
never talks to the DeepSeek API. ``ScriptedTestModel`` lets us feed specific
arguments to the tools exercised by each orchestrator.

The DB is backed by an in-memory SQLite engine shared across tests; tables
are truncated between tests for isolation. The lifespan's real
``init_db`` / ``dispose_db`` are stubbed so the production DATABASE_URL is
never touched.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel
from sqlalchemy import delete
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.core.db as db_module
import app.features.memory.models  # noqa: F401 -- registers ORM on Base.metadata
import app.features.skills.skills.skills as skill_factory_module
import app.features.tools.tools as tools_tools_module
from app.core.db import Base, get_session
from app.features.chat.agent import chat_agent
from app.features.extract.agent import extract_agent
from app.features.memory.agent import memory_agent
from app.features.memory.models import Conversation, Message
from app.features.skills.agent import skills_agent
from app.features.tasks.orchestrator import tasks_agent
from app.features.tools.agent import tools_agent
from app.main import app as fastapi_app

# ----- Shared in-memory SQLite engine for the test session -----------------
_test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
_test_session_maker = async_sessionmaker(_test_engine, expire_on_commit=False)


def _create_schema() -> None:
    async def _go() -> None:
        async with _test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_go())


def _truncate() -> None:
    async def _go() -> None:
        async with _test_engine.begin() as conn:
            await conn.execute(delete(Message))
            await conn.execute(delete(Conversation))

    asyncio.run(_go())


_create_schema()


async def _override_get_session() -> AsyncIterator:
    async with _test_session_maker() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(fastapi_app) as c:
        yield c


class ScriptedTestModel(TestModel):
    """``TestModel`` that returns hand-picked args for chosen tools."""

    def __init__(
        self,
        *,
        call_tools: list[str] | Literal["all"],
        tool_args: dict[str, Any] | None = None,
        custom_output_text: str | None = None,
    ) -> None:
        super().__init__(call_tools=call_tools, custom_output_text=custom_output_text)
        self._tool_args = tool_args or {}

    def gen_tool_args(self, tool_def):  # type: ignore[no-untyped-def]
        if tool_def.name in self._tool_args:
            return self._tool_args[tool_def.name]
        return super().gen_tool_args(tool_def)


@pytest.fixture(autouse=True)
def patch_models(monkeypatch) -> Iterator[None]:
    # Default model for dynamically-built skill agents.
    monkeypatch.setattr(
        skill_factory_module,
        "get_model",
        lambda: TestModel(custom_output_text="skill-output"),
    )

    chat_agent._model = TestModel(custom_output_text="chat-response")
    memory_agent._model = TestModel(custom_output_text="memory-response")
    extract_agent._model = TestModel()

    tools_agent._model = ScriptedTestModel(
        call_tools=["calculator", "current_time"],
        tool_args={"calculator": {"expression": "1+1"}},
        custom_output_text="tools-done",
    )

    skills_agent._model = ScriptedTestModel(
        call_tools=["dispatch_skill"],
        tool_args={
            "dispatch_skill": {
                "skill_name": "summarizer",
                "input_text": "Hello world. This is a test.",
            }
        },
        custom_output_text="skills-done",
    )

    tasks_agent._model = ScriptedTestModel(
        call_tools=["delegate_chat"],
        tool_args={"delegate_chat": {"subtask": "greet the user"}},
        custom_output_text="tasks-done",
    )

    # Safety net so the fetch tool never touches the network.
    monkeypatch.setattr(tools_tools_module, "http_fetch", lambda *a, **k: "stub-body")

    # Point the DB layer at the test engine and stub the lifespan hooks so the
    # production DATABASE_URL is never opened.
    monkeypatch.setattr(db_module, "_engine", _test_engine)
    monkeypatch.setattr(db_module, "_session_maker", _test_session_maker)
    import app.main as main_module

    monkeypatch.setattr(main_module, "init_db", lambda *a, **k: None)

    async def _noop_dispose() -> None:
        return None

    monkeypatch.setattr(main_module, "dispose_db", _noop_dispose)
    fastapi_app.dependency_overrides[get_session] = _override_get_session

    yield

    fastapi_app.dependency_overrides.pop(get_session, None)
    _truncate()
