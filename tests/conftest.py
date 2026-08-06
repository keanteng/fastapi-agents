"""Test fixtures.

The DB is backed by an in-memory SQLite engine shared across tests; tables
are truncated between tests for isolation. The lifespan's real ``init_db`` /
``dispose_db`` are stubbed so the production DATABASE_URL is never touched.

Models: every agent built by ``app.agents.build`` (including dynamically built
skill and delegation sub-agents) uses pydantic-ai ``TestModel``. Tests that
need specific tool calls or output text set the model per-test with the
``agent_model`` fixture.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.agents.build as build_module
import app.agents.memory.models  # noqa: F401 -- registers ORM on Base.metadata
import app.agents.skills as skills_module
import app.agents.tools as tools_module
import app.core.db as db_module
import app.features.skills.skills.skills as skill_factory_module  # legacy slice
import app.features.tools.tools as tools_tools_module  # legacy slice
from app.agents.memory.models import Conversation, Message
from app.core.db import Base, get_session
from app.features.chat.agent import chat_agent
from app.features.extract.agent import extract_agent
from app.features.memory.agent import memory_agent
from app.features.skills.agent import skills_agent
from app.features.tasks.orchestrator import tasks_agent
from app.features.tools.agent import tools_agent
from app.main import app as fastapi_app

# ----- Shared SQLite engine for the test session -----------------------------
# A temp-file DB (not ``:memory:``): aiosqlite connections that are invalidated
# when a run task is cancelled mid-flight would otherwise destroy an in-memory
# database (the schema lives in the connection). A file keeps the schema across
# connection churn. StaticPool still pins a single connection.
_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="agents-test-"))
_TEST_DB_PATH = _TEST_DB_DIR / "test.db"

_test_engine = create_async_engine(
    f"sqlite+aiosqlite:///{_TEST_DB_PATH}",
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


def wait_for_status(
    client: TestClient, run_id: str, expected: str, timeout: float = 3.0
) -> dict:
    """Poll ``GET /api/v1/runs/{run_id}`` until ``status == expected``."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] == expected:
            return body
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} never reached status {expected!r}")


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


class _ModelHolder:
    current: Any = None


_model_holder = _ModelHolder()


@pytest.fixture
def agent_model() -> Iterator[Any]:
    """Set the model ``build_agent`` uses for the duration of a test."""

    def set_model(model: Any) -> None:
        _model_holder.current = model

    yield set_model
    _model_holder.current = None


@pytest.fixture(autouse=True)
def patch_models(monkeypatch) -> Iterator[None]:
    # Every agent built by build_agent gets TestModel (per-test override via
    # the ``agent_model`` fixture). The default TestModel calls no tools so a
    # plain generalist run completes instead of hitting tools with junk args.
    monkeypatch.setattr(
        build_module,
        "get_model",
        lambda: (
            _model_holder.current
            if _model_holder.current is not None
            else TestModel(call_tools=[])
        ),
    )
    monkeypatch.setattr(
        skills_module,
        "get_model",
        lambda: TestModel(custom_output_text="skill-output"),
    )

    # Legacy slice: keep the old slice agents on TestModel until they are deleted.
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

    # Safety net so no fetch tool ever touches the network.
    monkeypatch.setattr(tools_tools_module, "http_fetch", lambda *a, **k: "stub-body")

    async def _stub_http_fetch(url: str, *, timeout: float = 10.0) -> str:
        return "stub-body"

    monkeypatch.setattr(tools_module, "http_fetch", _stub_http_fetch)

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
