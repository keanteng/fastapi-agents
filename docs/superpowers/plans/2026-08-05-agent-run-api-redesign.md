# Agent-Run API + MCP Server Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-subagent-driven-development (recommended) or superpowers-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the twelve endpoint-per-capability endpoints with a run-centric Agent-Protocol-style API (`POST/GET /api/v1/runs`, `GET /runs/{id}`, `GET /runs/{id}/events` SSE, `POST /runs/{id}/cancel`, `GET /api/v1/agents[/{name}]`), a consistent `{error:{code,message,details,run_id}}` envelope, an OpenAI-Responses-shaped SSE event stream, an in-memory run registry + asyncio runner, and a standalone FastMCP stdio server sharing the same tool callables.

**Architecture:** Three layers: a public HTTP layer (`app/api/{runs,agents,errors}.py`), a run domain (`app/runs/{models,registry,runner,events,sse}.py`), and an agent layer (`app/agents/` — declarative YAML specs, registry, builder, shared tools/skills/delegation, internal memory). Tools live once in `app/agents/tools.py`/`app/agents/skills.py`; the agent layer and the MCP server are thin adapters. Runs are in-process asyncio tasks in an in-memory registry guarded by a single `asyncio.Lock`; events are stored in a bounded deque for SSE replay; there is exactly one SSE subscriber per run. All tests use pydantic-ai `TestModel`/`ScriptedTestModel`, in-memory SQLite, and a stubbed `http_fetch` — no network.

**Tech Stack:** FastAPI, pydantic-ai 2.9 (`Agent`, `run_stream`, `Tool`, `TestModel`, event-stream handler), `mcp` SDK (FastMCP, stdio), `sse-starlette`, SQLAlchemy async + aiosqlite (tests), pydantic-settings, Jinja2 + PyYAML prompt catalog, pytest / pytest-asyncio.

---

## Task 0: Repo prep — dependency floor bump

> Status: COMPLETE (commit `eea190e`)

**Files:**
- Modify: `pyproject.toml` (dependencies block, lines 7-21)
- Regenerated: `uv.lock` (via `uv sync`, never hand-edited)

- [x] **Step 1: Bump the pydantic-ai floor and add `mcp`**

In `pyproject.toml`, change the dependencies block from:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "pydantic-ai[openai]>=0.6",
    "jinja2>=3.1",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "sse-starlette>=2.1",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "psycopg2-binary>=2.9",
]
```

to:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "pydantic-ai[openai]>=2.9.0",
    "jinja2>=3.1",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "mcp>=1.28",
    "sse-starlette>=2.1",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "psycopg2-binary>=2.9",
]
```

- [x] **Step 2: Resync the lockfile**

Run: `uv sync`
Expected: completes without error; `uv.lock` is updated to pin `mcp` and the raised `pydantic-ai` floor.

- [x] **Step 3: Confirm the baseline suite is still green**

Run: `uv run pytest -q`
Expected: `12 passed` (unchanged; nothing else was touched).

- [x] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: bump pydantic-ai floor to >=2.9.0 and add mcp>=1.28"
```

---

## Task 1: New package skeleton + error envelope

> Status: COMPLETE (commit `4af5ec9`; reviewer APPROVED)

**Files:**
- Create: `app/agents/__init__.py`
- Create: `app/runs/__init__.py`
- Create: `app/api/__init__.py`
- Create: `app/runs/models.py` (contains `ErrorBody` only — extended in Task 5)
- Create: `app/api/errors.py`
- Test: `tests/test_error_envelope.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_error_envelope.py`:

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.errors import AppError, register_error_handlers


class Item(BaseModel):
    x: int


def _make_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/validate")
    async def validate(body: Item) -> dict:
        return {"ok": body.x}

    @app.get("/app-error")
    async def app_error() -> None:
        raise AppError(404, "run_not_found", "run abc does not exist", run_id="abc")

    @app.get("/internal")
    async def internal() -> None:
        raise RuntimeError("boom")

    return app


def test_app_error_envelope() -> None:
    client = TestClient(_make_app())
    response = client.get("/app-error")
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "run_not_found",
            "message": "run abc does not exist",
            "details": None,
            "run_id": "abc",
        }
    }


def test_validation_error_envelope() -> None:
    client = TestClient(_make_app())
    response = client.post("/validate", json={})
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == "validation_error"
    assert error["run_id"] is None
    assert any(entry["loc"] == ["body", "x"] for entry in error["details"])


def test_internal_error_envelope() -> None:
    client = TestClient(_make_app(), raise_server_exceptions=False)
    response = client.get("/internal")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "internal server error",
            "details": None,
            "run_id": None,
        }
    }
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_error_envelope.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.errors'` (import at the top of the test file).

- [x] **Step 3: Write the skeleton package files**

Create `app/agents/__init__.py`:

```python
"""Agent layer: declarative specs, registry, builder, shared tools and skills."""
```

Create `app/runs/__init__.py`:

```python
"""Run domain: models, in-memory registry, runner, events and SSE."""
```

Create `app/api/__init__.py`:

```python
"""Public HTTP layer."""
```

- [x] **Step 4: Create `app/runs/models.py` with `ErrorBody`**

Create `app/runs/models.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    run_id: str | None = None
```

(Note: this file is fully rewritten in Task 5 with the rest of the run models; `ErrorBody` stays identical.)

- [x] **Step 5: Create `app/api/errors.py`**

Create `app/api/errors.py`:

```python
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.runs.models import ErrorBody

logger = logging.getLogger(__name__)


class AppError(Exception):
    """An HTTP error carrying the machine-readable error-envelope fields."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details=None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.run_id = run_id


def register_error_handlers(app: FastAPI) -> None:
    """Wire the error-envelope handlers (incl. the FastAPI 422 override)."""

    @app.exception_handler(AppError)
    async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        body = ErrorBody(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            run_id=exc.run_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": body.model_dump(mode="json")},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        body = ErrorBody(
            code="validation_error",
            message="request validation failed",
            details=jsonable_encoder(exc.errors()),
            run_id=None,
        )
        return JSONResponse(
            status_code=422,
            content={"error": body.model_dump(mode="json")},
        )

    @app.exception_handler(Exception)
    async def _internal_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        body = ErrorBody(
            code="internal_error",
            message="internal server error",
            details=None,
            run_id=None,
        )
        return JSONResponse(
            status_code=500,
            content={"error": body.model_dump(mode="json")},
        )
```

- [x] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_error_envelope.py -v`
Expected: `3 passed`.

- [x] **Step 7: Run the whole suite to confirm nothing regressed**

Run: `uv run pytest -q`
Expected: `15 passed` (12 baseline + 3 new).

- [x] **Step 8: Commit**

```bash
git add app/agents/__init__.py app/runs/__init__.py app/api/__init__.py app/runs/models.py app/api/errors.py tests/test_error_envelope.py
git commit -m "feat: add agents/runs/api package skeleton and error envelope"
```

---

## Task 2: Shared tools + skills + dual-mode conftest

> Status: COMPLETE (commits `a0818f2`, `7166f3a`, `86b611d`; reviewer APPROVED)
> Approved deviations from the verbatim code below: (1) `tests/test_tools.py` calls
> `tools_module.http_fetch(...)` via module attribute instead of the bare import, because the
> conftest patches the module attribute at runtime; (2) `tests/conftest.py`'s new-layer fetch
> stub is an `async def` (the new `http_fetch` is a coroutine function). Both were required to
> make the network-stub effective; `app/agents/tools.py` and `app/agents/skills.py` are byte-for-byte as written.

**Files:**
- Create: `app/agents/tools.py`
- Create: `app/agents/skills.py`
- Modify: `tests/conftest.py` (full rewrite — keeps legacy slice patches, adds new-layer patches)
- Rewrite: `tests/test_tools.py`
- Rewrite: `tests/test_skills.py`

- [x] **Step 1: Write the failing tool tests**

Rewrite `tests/test_tools.py`:

```python
from __future__ import annotations

import asyncio

import pytest
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.models.test import TestModel

from app.agents.tools import (
    calculator,
    current_time,
    http_fetch,
    safe_eval,
    tool_adapter,
)


def test_safe_eval_basic() -> None:
    assert safe_eval("(1+2)*3") == 9


def test_safe_eval_rejects_imports_and_names() -> None:
    with pytest.raises(ValueError):
        safe_eval("__import__('os')")
    with pytest.raises(ValueError):
        safe_eval("os.system('ls')")


def test_calculator() -> None:
    assert calculator("1+1") == "2"


def test_current_time_is_iso_utc() -> None:
    value = current_time()
    assert value.endswith("Z") or "+00:00" in value
    from datetime import datetime

    datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_http_fetch_is_stubbed() -> None:
    # The autouse conftest patch replaces http_fetch with a stub, so this
    # never touches the network.
    assert asyncio.run(http_fetch("http://example.com")) == "stub-body"


async def test_tool_adapter_converts_errors_to_model_retry() -> None:
    def _boom(x: str) -> str:
        raise ValueError("nope")

    agent = Agent(
        TestModel(call_tools=["boom"], custom_output_text="x"),
        tools=[tool_adapter(_boom, "boom")],
        output_type=str,
    )
    tool = agent.toolsets[0].tools["boom"]
    with pytest.raises(ModelRetry):
        await tool.function(x="hi")
```

- [x] **Step 2: Run the tool tests to verify they fail**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.tools'`.

- [x] **Step 3: Write the failing skill tests**

Rewrite `tests/test_skills.py`:

```python
from __future__ import annotations

import pytest

from app.agents.skills import available_skills, dispatch_skill, get_skill
from app.core.prompts import get_engine


def test_available_skills() -> None:
    assert set(available_skills()) == {"summarizer", "translator", "code_reviewer"}


def test_get_skill_case_insensitive() -> None:
    skill = get_skill("Summarizer")
    assert skill is not None
    assert skill[0] == "Summarise a piece of text into a few key bullet points."


def test_skill_prompt_templates_render() -> None:
    engine = get_engine()
    assert "summar" in engine.render("skill_summarizer").lower()
    assert "translator" in engine.render("skill_translator").lower()
    assert "review" in engine.render("skill_code_reviewer").lower()


async def test_dispatch_skill_runs_subagent() -> None:
    # The autouse conftest patch points skills.get_model at TestModel, so
    # dispatch_skill returns the canned "skill-output" text.
    output = await dispatch_skill("summarizer", "Hello world. This is a test.")
    assert output == "skill-output"


async def test_dispatch_skill_unknown_raises() -> None:
    with pytest.raises(ValueError):
        await dispatch_skill("does-not-exist", "text")
```

- [x] **Step 4: Run the skill tests to verify they fail**

Run: `uv run pytest tests/test_skills.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.skills'`.

- [x] **Step 5: Create `app/agents/tools.py`**

Create `app/agents/tools.py`:

```python
from __future__ import annotations

import ast
import functools
import inspect
import operator
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic_ai import ModelRetry
from pydantic_ai.tools import Tool

# --------------------------------------------------------------------------- #
# Safe arithmetic evaluator
# --------------------------------------------------------------------------- #

_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS: dict[type, Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _eval(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def safe_eval(expression: str) -> float | int:
    tree = ast.parse(expression, mode="eval")
    return _eval(tree)


async def http_fetch(url: str, *, timeout: float = 10.0) -> str:
    """Fetch up to 4096 chars of text from an HTTP URL."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url)
        response.raise_for_status()
    return response.text[:4096]


def calculator(expression: str) -> str:
    """Evaluate a numeric expression and return the result as a string."""
    return str(safe_eval(expression))


def current_time() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Shared tool registry + pydantic-ai adapter (single source of truth)
# --------------------------------------------------------------------------- #


def shared_tools() -> dict[str, Callable]:
    """The shared tool callables by public name (single source of truth)."""
    return {
        "calculator": calculator,
        "fetch": http_fetch,
        "current_time": current_time,
    }


def tool_adapter(fn: Callable, name: str) -> Tool:
    """Wrap a plain shared callable as a pydantic-ai ``Tool``.

    Plain callables raise ordinary exceptions; this adapter converts them into
    ``ModelRetry`` so the model can self-correct (pydantic-ai idiom).
    """
    is_async = inspect.iscoroutinefunction(fn)

    @functools.wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            if is_async:
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)
        except ModelRetry:
            raise
        except Exception as exc:  # noqa: BLE001 - surface to the model via retry
            raise ModelRetry(f"{name} failed: {exc}") from exc

    return Tool(wrapped, name=name)
```

- [x] **Step 6: Create `app/agents/skills.py`**

Create `app/agents/skills.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from pydantic_ai import Agent

from app.core.model import get_model
from app.core.prompts import render


def _skill_agent(prompt_task: str) -> Agent[None, str]:
    return Agent(
        get_model(),
        instructions=lambda _: render(prompt_task),
        output_type=str,
    )


def summarizer_skill() -> Agent[None, str]:
    return _skill_agent("skill_summarizer")


def translator_skill() -> Agent[None, str]:
    return _skill_agent("skill_translator")


def code_reviewer_skill() -> Agent[None, str]:
    return _skill_agent("skill_code_reviewer")


SKILL_FACTORIES: dict[str, tuple[str, Callable[[], Agent[None, str]]]] = {
    "summarizer": (
        "Summarise a piece of text into a few key bullet points.",
        summarizer_skill,
    ),
    "translator": (
        "Translate text into a target language (default: French).",
        translator_skill,
    ),
    "code_reviewer": (
        "Review a small code snippet and surface issues.",
        code_reviewer_skill,
    ),
}


def available_skills() -> dict[str, str]:
    return {name: desc for name, (desc, _factory) in SKILL_FACTORIES.items()}


def get_skill(name: str) -> tuple[str, Callable[[], Agent[None, str]]] | None:
    if name in SKILL_FACTORIES:
        return SKILL_FACTORIES[name]
    lower = name.lower()
    for key, value in SKILL_FACTORIES.items():
        if key.lower() == lower:
            return value
    return None


async def dispatch_skill(skill_name: str, input_text: str) -> str:
    """Run the named skill sub-agent on ``input_text`` and return its output.

    Shared callable for the run API (via ``tool_adapter``) and the MCP server
    (via ``@mcp.tool``). Raises ``ValueError`` for unknown skills.
    """
    skill = get_skill(skill_name)
    if skill is None:
        raise ValueError(
            f"unknown skill {skill_name!r}. Available: {sorted(available_skills())}"
        )
    _desc, factory = skill
    agent = factory()
    async with agent:
        result = await agent.run(input_text)
    return result.output
```

- [x] **Step 7: Rewrite `tests/conftest.py` (dual-mode)**

Replace the entire contents of `tests/conftest.py` with:

```python
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
from collections.abc import AsyncIterator, Iterator
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models.test import TestModel
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.agents.skills as skills_module
import app.agents.tools as tools_module
import app.core.db as db_module
import app.features.memory.models  # noqa: F401 -- registers ORM on Base.metadata
import app.features.skills.skills.skills as skill_factory_module  # legacy slice
import app.features.tools.tools as tools_tools_module  # legacy slice
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


def wait_for_status(client: TestClient, run_id: str, expected: str, timeout: float = 3.0) -> dict:
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
    # New layer: skill factories get TestModel. ``app.agents.build`` gets its
    # TestModel patch added in Task 3 (when that module is created).
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
    monkeypatch.setattr(tools_module, "http_fetch", lambda *a, **k: "stub-body")

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
```

- [x] **Step 8: Run the tool and skill tests**

Run: `uv run pytest tests/test_tools.py tests/test_skills.py -v`
Expected: both files pass (11 tests total).

- [x] **Step 9: Run the whole suite to confirm the legacy tests still pass**

Run: `uv run pytest -q`
Expected: `23 passed` (12 legacy + 3 envelope + 11 new minus the 3 replaced legacy endpoint tests).

- [x] **Step 10: Commit**

```bash
git add app/agents/tools.py app/agents/skills.py tests/conftest.py tests/test_tools.py tests/test_skills.py
git commit -m "feat: add shared tools and skills modules (pydantic-ai 2.x)"
```

---

## Task 3: Agent specs, registry, builder, templates

> Status: COMPLETE (uncommitted; deviates from the plan's test ordering in three tests so `agent_model` is set before `build_agent`, since the model resolves eagerly; conftest fetch stub keeps the real `http_fetch` signature)

**Files:**
- Create: `app/agents/definitions.py`
- Create: `app/agents/models/__init__.py`
- Create: `app/agents/models/extraction.py`
- Create: `app/agents/delegation.py`
- Create: `app/agents/build.py`
- Create: `app/agents/registry.py`
- Create: `app/agents/specs/generalist.yaml`
- Create: `app/agents/specs/extractor.yaml`
- Create: `app/agents/templates/generalist/system.jinja`
- Create: `app/agents/templates/extractor/system.jinja`
- Create: `app/agents/templates/skills/summarizer.jinja`
- Create: `app/agents/templates/skills/translator.jinja`
- Create: `app/agents/templates/skills/code_reviewer.jinja`
- Modify: `app/core/prompts.yml` (add `generalist`/`extractor`, repoint `skill_*` paths)
- Modify: `app/core/container.py` (add `agents: AgentRegistry` to the container)
- Test: `tests/test_agents_registry.py`

- [x] **Step 1: Write the failing tests**

Create `tests/test_agents_registry.py`:

```python
from __future__ import annotations

import asyncio

import pytest
from pydantic_ai import Agent

from app.agents.definitions import AgentDefinition
from app.agents.registry import load_agent_registry


def test_registry_loads_both_agents() -> None:
    registry = load_agent_registry()
    assert set(registry.definitions) == {"generalist", "extractor"}
    assert registry.definitions["generalist"].uses_memory is True
    assert registry.definitions["generalist"].output_type == "string"
    assert registry.definitions["extractor"].output_type == "structured_output"


def test_registry_tools_include_shared_and_delegation() -> None:
    registry = load_agent_registry()
    assert set(registry.tools) == {
        "calculator",
        "fetch",
        "current_time",
        "dispatch_skill",
        "delegate_chat",
        "delegate_tools",
        "delegate_skill",
    }


def test_agent_definition_validates() -> None:
    definition = AgentDefinition.model_validate(
        {
            "name": "x",
            "description": "d",
            "instructions": "generalist",
            "output_type": "string",
            "tools": ["calculator"],
            "capabilities": ["thinking"],
            "uses_memory": True,
            "default_max_steps": 8,
        }
    )
    assert definition.name == "x"
    assert definition.capabilities == ["thinking"]


def test_build_agent_generalist_is_agent() -> None:
    registry = load_agent_registry()
    agent = registry.build_agent("generalist")
    assert isinstance(agent, Agent)


def test_build_agent_unknown_raises() -> None:
    registry = load_agent_registry()
    with pytest.raises(KeyError):
        registry.build_agent("nope")


def test_build_agent_extractor_output_model() -> None:
    from app.agents.models.extraction import ExtractionResult

    registry = load_agent_registry()
    agent = registry.build_agent("extractor")
    assert agent.output_type is ExtractionResult


def test_build_agent_tool_filtering(agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    registry = load_agent_registry()
    agent = registry.build_agent("generalist", tools=["calculator"])
    agent_model(
        ScriptedTestModel(
            call_tools=["calculator"],
            tool_args={"calculator": {"expression": "1+1"}},
            custom_output_text="done",
        )
    )

    async def _run() -> str:
        async with agent:
            result = await agent.run("what is 1+1")
        return result.output

    assert asyncio.run(_run()) == "done"


def test_build_agent_ignores_unknown_capabilities(agent_model) -> None:
    from pydantic_ai.models.test import TestModel

    registry = load_agent_registry()
    agent = registry.build_agent("generalist", capabilities=["does-not-exist"])
    agent_model(TestModel(custom_output_text="ok"))

    async def _run() -> str:
        async with agent:
            result = await agent.run("hi")
        return result.output

    assert asyncio.run(_run()) == "ok"


def test_build_agent_delegation_runs(agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    registry = load_agent_registry()
    agent = registry.build_agent("generalist")
    agent_model(
        ScriptedTestModel(
            call_tools="all",
            tool_args={
                "calculator": {"expression": "1+1"},
                "fetch": {"url": "http://example.com"},
                "current_time": {},
                "dispatch_skill": {"skill_name": "summarizer", "input_text": "hello"},
                "delegate_chat": {"subtask": "chat sub"},
                "delegate_tools": {"subtask": "tool sub"},
                "delegate_skill": {"skill_name": "summarizer", "input_text": "hello"},
            },
            custom_output_text="outer-done",
        )
    )

    async def _run() -> str:
        async with agent:
            result = await agent.run("do everything")
        return result.output

    assert asyncio.run(_run()) == "outer-done"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agents_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.definitions'`.

- [x] **Step 3: Create the definition model**

Create `app/agents/definitions.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentDefinition(BaseModel):
    """Declarative agent spec loaded from ``app/agents/specs/*.yaml``."""

    name: str
    description: str
    instructions: str = Field(..., description="Key into app/core/prompts.yml.")
    model: str | None = None  # null -> settings.deepseek_model
    output_type: Literal["string", "structured_output"] = "string"
    output_schema: dict[str, Any] | None = None  # JSON schema when structured_output
    capabilities: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    uses_memory: bool = False
    default_max_steps: int = 8
```

- [x] **Step 4: Create the extraction models**

Create `app/agents/models/__init__.py`:

```python
"""Shared pydantic output models."""
```

Create `app/agents/models/extraction.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class Entity(BaseModel):
    name: str = Field(..., description="The entity's surface form.")
    type: str = Field(..., description="PER, ORG, LOC, DATE, MISC.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    """Structured output the agent must return."""

    entities: list[Entity] = Field(default_factory=list)
    language: str | None = Field(
        default=None, description="Detected dominant language code (e.g. 'en')."
    )
    summary: str = Field(default="", description="One-sentence summary of the input.")
```

- [x] **Step 5: Create the delegation tools**

Create `app/agents/delegation.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from app.agents.skills import dispatch_skill


def make_delegate_tools(build_agent: Callable) -> dict[str, Callable]:
    """Build the sub-agent delegation tools for the generalist agent.

    Each delegate tool runs a fresh generalist that has only the base tools
    (no delegation), so delegation cannot recurse.
    """

    async def delegate_chat(subtask: str) -> str:
        """Delegate a general conversational sub-task to a fresh generalist."""
        agent = build_agent(
            "generalist",
            tools=["calculator", "fetch", "current_time", "dispatch_skill"],
        )
        async with agent:
            result = await agent.run(subtask)
        return result.output

    async def delegate_tools(subtask: str) -> str:
        """Delegate a tool-needing sub-task to a fresh generalist."""
        agent = build_agent(
            "generalist",
            tools=["calculator", "fetch", "current_time", "dispatch_skill"],
        )
        async with agent:
            result = await agent.run(subtask)
        return result.output

    async def delegate_skill(skill_name: str, input_text: str) -> str:
        """Delegate a sub-task to a registered skill sub-agent."""
        return await dispatch_skill(skill_name, input_text)

    return {
        "delegate_chat": delegate_chat,
        "delegate_tools": delegate_tools,
        "delegate_skill": delegate_skill,
    }
```

- [x] **Step 6: Create the agent builder**

Create `app/agents/build.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.capabilities.thinking import Thinking

from app.agents.definitions import AgentDefinition
from app.agents.models.extraction import ExtractionResult
from app.agents.tools import tool_adapter
from app.core.model import get_model
from app.core.prompts import render

_CAPABILITY_FACTORIES: dict[str, Callable[[], Any]] = {
    "thinking": Thinking,
}

_STRUCTURED_MODELS: dict[str, type[Any]] = {
    "ExtractionResult": ExtractionResult,
}


def resolve_output_model(schema: dict[str, Any] | None) -> Any:
    """Map an agent spec's ``output_schema`` to a pydantic output model."""
    if schema is None:
        return str
    title = schema.get("title")
    model = _STRUCTURED_MODELS.get(title)  # type: ignore[arg-type]
    if model is None:
        raise ValueError(
            f"no pydantic model registered for output schema title {title!r}"
        )
    return model


def resolve_capabilities(
    definition: AgentDefinition, hints: list[str] | None
) -> list[Any]:
    """Resolve requested capability names against the spec's declared set."""
    declared = set(definition.capabilities)
    names = set(hints) & declared if hints is not None else declared
    return [
        _CAPABILITY_FACTORIES[name]()
        for name in sorted(names)
        if name in _CAPABILITY_FACTORIES
    ]


def build_agent(
    definition: AgentDefinition,
    tools: dict[str, Callable],
    capabilities: list[str] | None = None,
    model: Any | None = None,
) -> Agent[None, Any]:
    """Build a pydantic-ai ``Agent`` from a declarative spec."""
    resolved_model = model or get_model()
    registered_tools = [tool_adapter(fn, name) for name, fn in tools.items()]
    output_type = resolve_output_model(definition.output_schema)
    return Agent(
        resolved_model,
        instructions=lambda _: render(definition.instructions),
        output_type=output_type,
        tools=registered_tools,
        capabilities=resolve_capabilities(definition, capabilities),
        name=definition.name,
    )
```

- [x] **Step 7: Create the agent registry**

Create `app/agents/registry.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from yaml import safe_load

from app.agents import build
from app.agents.definitions import AgentDefinition
from app.agents.delegation import make_delegate_tools
from app.agents.skills import dispatch_skill

SPECS_DIR = Path(__file__).resolve().parent / "specs"


class AgentRegistry:
    """Holds declarative agent definitions and the shared tool callables."""

    def __init__(self, definitions: dict[str, AgentDefinition]) -> None:
        self.definitions = definitions
        self.tools: dict[str, Callable] = {}
        self._init_tools()

    def _init_tools(self) -> None:
        from app.agents import tools as tools_module

        self.tools = {
            "calculator": tools_module.calculator,
            "fetch": tools_module.http_fetch,
            "current_time": tools_module.current_time,
            "dispatch_skill": dispatch_skill,
        }
        self.tools.update(make_delegate_tools(self.build_agent))

    def build_agent(
        self,
        name: str,
        tools: list[str] | None = None,
        capabilities: list[str] | None = None,
        model: Any | None = None,
    ) -> Agent:
        """Resolve a spec and build a pydantic-ai ``Agent`` for one run."""
        definition = self.definitions.get(name)
        if definition is None:
            raise KeyError(name)
        requested = tools if tools is not None else definition.tools
        effective_names = [n for n in requested if n in self.tools]
        resolved_tools = {n: self.tools[n] for n in effective_names}
        return build.build_agent(definition, resolved_tools, capabilities, model)


def load_agent_registry() -> AgentRegistry:
    """Load every ``app/agents/specs/*.yaml`` file into an ``AgentRegistry``."""
    definitions: dict[str, AgentDefinition] = {}
    for path in sorted(SPECS_DIR.glob("*.yaml")):
        data = safe_load(path.read_text(encoding="utf-8"))
        definition = AgentDefinition.model_validate(data)
        definitions[definition.name] = definition
    return AgentRegistry(definitions)
```

- [x] **Step 8: Create the agent spec YAML files**

Create `app/agents/specs/generalist.yaml`:

```yaml
name: generalist
description: "Conversational agent with tool calling, skill delegation, and memory."
instructions: generalist
model: null
output_type: string
output_schema: null
capabilities: [thinking]
tools: [calculator, fetch, current_time, dispatch_skill,
        delegate_chat, delegate_tools, delegate_skill]
uses_memory: true
default_max_steps: 8
```

Create `app/agents/specs/extractor.yaml`:

```yaml
name: extractor
description: "Structured entity-extraction agent with no tools and no memory."
instructions: extractor
model: null
output_type: structured_output
output_schema:
  title: ExtractionResult
  type: object
  description: Structured output the agent must return.
  properties:
    entities:
      title: Entities
      type: array
      items:
        $ref: "#/$defs/Entity"
    language:
      title: Language
      anyOf:
        - type: string
        - type: "null"
      default: null
      description: Detected dominant language code (e.g. 'en').
    summary:
      title: Summary
      type: string
      default: ""
      description: One-sentence summary of the input.
  $defs:
    Entity:
      title: Entity
      type: object
      properties:
        name:
          title: Name
          type: string
          description: The entity's surface form.
        type:
          title: Type
          type: string
          description: PER, ORG, LOC, DATE, MISC.
        confidence:
          title: Confidence
          type: number
          default: 0.0
          minimum: 0.0
          maximum: 1.0
      required: [name, type]
capabilities: []
tools: []
uses_memory: false
default_max_steps: 8
```

- [x] **Step 9: Create the prompt templates**

Create `app/agents/templates/generalist/system.jinja`:

```jinja
{% extends "core/templates/base.jinja" %}
{% block role %}general-purpose assistant{% endblock %}
{% block extra %}You can use tools for computation (calculator), fetching URLs (fetch), and
the current time (current_time). Use them rather than guessing.
You can dispatch registered skills (summarizer, translator, code_reviewer) via
dispatch_skill, and delegate sub-tasks via delegate_chat, delegate_tools and
delegate_skill.
Prior conversation history, when present, is provided as message history; use
it when answering.{% endblock %}
```

Create `app/agents/templates/extractor/system.jinja`:

```jinja
You are an entity extractor. From the user's text extract named entities into
the structured output schema. Use null for fields you cannot infer. Do not add
free text outside the schema.
```

Create `app/agents/templates/skills/summarizer.jinja`:

```jinja
You are a summariser. Read the user's text and return 3-5 concise bullet
points capturing the key ideas. Use plain markdown bullets (``- ``).
```

Create `app/agents/templates/skills/translator.jinja`:

```jinja
You are a translator. The user supplies text and an optional target language;
default to French. Return only the translation, no commentary.
```

Create `app/agents/templates/skills/code_reviewer.jinja`:

```jinja
You are a code reviewer. Review the user's snippet and list concrete issues
grouped as: Correctness, Style, Performance. Be terse. Suggest fixes.
```

- [x] **Step 10: Update `app/core/prompts.yml`**

Replace the entire contents of `app/core/prompts.yml` with:

```yaml
# Central prompt catalog.
# Maps a logical ``task`` (and optional ``variant``) to a template path and a
# version, so business code references prompts by name instead of file paths.
# Every path is validated at startup by ``PromptEngine``.

chat:
  default:
    path: "features/chat/templates/system.jinja"
    version: "1.0"
memory:
  default:
    path: "features/memory/templates/system.jinja"
    version: "1.0"
tools:
  default:
    path: "features/tools/templates/system.jinja"
    version: "1.0"
extract:
  default:
    path: "features/extract/templates/system.jinja"
    version: "1.0"
skills_orchestrator:
  default:
    path: "features/skills/templates/orchestrator.jinja"
    version: "1.0"
tasks_orchestrator:
  default:
    path: "features/tasks/templates/orchestrator.jinja"
    version: "1.0"
generalist:
  default:
    path: "agents/templates/generalist/system.jinja"
    version: "1.0"
extractor:
  default:
    path: "agents/templates/extractor/system.jinja"
    version: "1.0"
skill_summarizer:
  default:
    path: "agents/templates/skills/summarizer.jinja"
    version: "1.0"
skill_translator:
  default:
    path: "agents/templates/skills/translator.jinja"
    version: "1.0"
skill_code_reviewer:
  default:
    path: "agents/templates/skills/code_reviewer.jinja"
    version: "1.0"
```

(Note: the obsolete `chat`, `memory`, `tools`, `extract`, `skills_orchestrator`, and `tasks_orchestrator` keys are kept here because the legacy feature agents still render them; they are removed in Task 10 alongside `app/features/`.)

- [x] **Step 11: Add the agent registry to the container**

Replace the entire contents of `app/core/container.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from pydantic_ai.models.openai import OpenAIChatModel

from app.agents.registry import AgentRegistry, load_agent_registry
from app.core.config import Settings
from app.core.model import get_model
from app.core.prompts import PromptEngine


@dataclass
class AppContainer:
    """Root container holding process-wide singletons."""

    config: Settings
    model: OpenAIChatModel
    prompts: PromptEngine
    agents: AgentRegistry


_container: AppContainer | None = None


def build_container(config: Settings | None = None) -> AppContainer:
    """Construct and cache every application-scoped singleton."""
    global _container
    resolved = config or Settings()
    container = AppContainer(
        config=resolved,
        model=get_model(),
        prompts=PromptEngine(),
        agents=load_agent_registry(),
    )
    _container = container
    return container


def get_container() -> AppContainer:
    """Return the process-wide container, building it lazily if needed.

    The running server builds it explicitly in the lifespan; this lazy path
    covers scripts and tests that use the app outside a request lifecycle.
    """
    global _container
    if _container is None:
        build_container()
    assert _container is not None  # noqa: S101 -- for type checkers
    return _container


def get_container_from_request(request: Request) -> AppContainer:
    """FastAPI dependency yielding the container stored on ``app.state``."""
    return request.app.state.container


def close_container() -> None:
    """Drop the cached container (called on app shutdown)."""
    global _container
    _container = None
```

- [x] **Step 12: Wire the `build_agent` TestModel patch into the conftest**

In `tests/conftest.py`, make two edits.

Edit 1 — add `import app.agents.build as build_module` as the first line of the new-layer import block (currently `import app.agents.skills as skills_module` is the first line):

```python
import app.agents.build as build_module
import app.agents.skills as skills_module
import app.agents.tools as tools_module
import app.core.db as db_module
import app.features.memory.models  # noqa: F401 -- registers ORM on Base.metadata
```

Edit 2 — add the `build_module` patch at the top of `patch_models`:

```python
@pytest.fixture(autouse=True)
def patch_models(monkeypatch) -> Iterator[None]:
    # Every agent built by build_agent gets TestModel (per-test override via
    # the ``agent_model`` fixture).
    monkeypatch.setattr(
        build_module,
        "get_model",
        lambda: _model_holder.current if _model_holder.current is not None else TestModel(),
    )
    monkeypatch.setattr(
        skills_module,
        "get_model",
        lambda: TestModel(custom_output_text="skill-output"),
    )
```

- [x] **Step 13: Run the new tests**

Run: `uv run pytest tests/test_agents_registry.py -v`
Expected: `9 passed`.

- [x] **Step 14: Run the whole suite**

Run: `uv run pytest -q`
Expected: `32 passed` (23 + 9 new).

- [x] **Step 15: Commit**

```bash
git add app/agents/definitions.py app/agents/models/ app/agents/delegation.py app/agents/build.py app/agents/registry.py app/agents/specs/ app/agents/templates/ app/core/prompts.yml app/core/container.py tests/test_agents_registry.py tests/conftest.py
git commit -m "feat: add declarative agent specs, registry, and agent builder"
```

---

## Task 4: Move the memory layer under `app/agents/memory`

> Status: COMPLETE (committed; the legacy `features/memory/schemas.py` now aliases the moved `MessageOut`/`PartOut` so the legacy memory router keeps validating until Task 10)

**Files:**
- Move: `app/features/memory/models.py` → `app/agents/memory/models.py`
- Move: `app/features/memory/repository.py` → `app/agents/memory/repository.py`
- Move: `app/features/memory/serialize.py` → `app/agents/memory/serialize.py`
- Create: `app/agents/memory/__init__.py`
- Create: `app/agents/memory/schemas.py` (DTOs extracted from the legacy schemas; see note)
- Create: `app/agents/memory/wiring.py`
- Replace: `app/features/memory/models.py` with a shim
- Replace: `app/features/memory/repository.py` with a shim
- Replace: `app/features/memory/serialize.py` with a shim
- Modify: `app/core/migrations/env.py` (import path)
- Modify: `tests/conftest.py` (memory model imports)
- Modify: `tests/test_memory_repository.py` (import path + add wiring tests)

> Note on serialize.py: the public memory DTOs (`MessageOut`/`PartOut`) die with the legacy memory CRUD, but `serialize.py` still needs them. We move `MessageOut`/`PartOut` into `app/agents/memory/schemas.py` (new home) and point the moved `serialize.py` at it; the legacy `app/features/memory/schemas.py` stays untouched for the legacy router until Task 10.

- [x] **Step 1: Move the memory ORM models**

Run:

```bash
mkdir -p app/agents/memory
git mv app/features/memory/models.py app/agents/memory/models.py
git mv app/features/memory/repository.py app/agents/memory/repository.py
git mv app/features/memory/serialize.py app/agents/memory/serialize.py
```

- [x] **Step 2: Update the moved `repository.py` import**

In `app/agents/memory/repository.py`, change:

```python
from app.features.memory.models import Conversation, Message
```

to:

```python
from app.agents.memory.models import Conversation, Message
```

- [x] **Step 3: Create the DTO home and update the moved `serialize.py`**

Create `app/agents/memory/schemas.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PartOut(BaseModel):
    kind: str = Field(
        ..., description="pydantic-ai part_kind, e.g. user-prompt/tool-call."
    )
    role: str = Field(
        ..., description="Stable role: user|assistant|system|tool|unknown."
    )
    content: str | None = Field(
        default=None, description="Text content for text-like parts."
    )
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_call_id: str | None = None
    tool_result: Any | None = None
    timestamp: datetime | None = None


class MessageOut(BaseModel):
    kind: str = Field(
        ..., description="request|response (mirrors ModelRequest/ModelResponse)."
    )
    parts: list[PartOut] = Field(default_factory=list)
```

In `app/agents/memory/serialize.py`, change:

```python
from app.features.memory.schemas import MessageOut, PartOut
```

to:

```python
from app.agents.memory.schemas import MessageOut, PartOut
```

- [x] **Step 4: Replace the legacy files with shims**

Replace `app/features/memory/models.py` with:

```python
# Legacy shim — the ORM models now live in app.agents.memory.models.
from app.agents.memory.models import Conversation, Message  # noqa: F401
```

Replace `app/features/memory/repository.py` with:

```python
# Legacy shim — the repository now lives in app.agents.memory.repository.
from app.agents.memory.repository import MemoryRepository  # noqa: F401
```

Replace `app/features/memory/serialize.py` with:

```python
# Legacy shim — the serializer now lives in app.agents.memory.serialize.
from app.agents.memory.serialize import MessageOut, PartOut, to_dto  # noqa: F401
```

- [x] **Step 5: Create the wiring helpers**

Create `app/agents/memory/__init__.py`:

```python
"""Internal conversation memory: ORM, repository, serialization, wiring."""
```

Create `app/agents/memory/wiring.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.agents.memory.repository import MemoryRepository
from app.core.db import get_session_maker


async def load_history(conversation_id: str) -> list[Any]:
    """Load persisted message history for a conversation."""
    session = get_session_maker()()
    try:
        return await MemoryRepository(session).get(conversation_id)
    finally:
        await session.close()


async def persist_history(conversation_id: str, messages: Sequence[Any]) -> None:
    """Persist a full turn of messages for a conversation (replaces history)."""
    session = get_session_maker()()
    try:
        await MemoryRepository(session).set(conversation_id, messages)
        await session.commit()
    finally:
        await session.close()
```

- [x] **Step 6: Update the Alembic migration wiring**

In `app/core/migrations/env.py`, change:

```python
from app.features.memory import models as _memory_models  # noqa: F401
```

to:

```python
from app.agents.memory import models as _memory_models  # noqa: F401
```

- [x] **Step 7: Update `tests/conftest.py` memory imports**

In `tests/conftest.py`, change:

```python
import app.features.memory.models  # noqa: F401 -- registers ORM on Base.metadata
```

to:

```python
import app.agents.memory.models  # noqa: F401 -- registers ORM on Base.metadata
```

and change:

```python
from app.features.memory.models import Conversation, Message
```

to:

```python
from app.agents.memory.models import Conversation, Message
```

- [x] **Step 8: Update and extend the repository tests**

Replace the entire contents of `tests/test_memory_repository.py` with:

```python
"""Repository + wiring tests using the shared in-memory SQLite engine."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.memory.repository import MemoryRepository
from app.agents.memory.wiring import load_history, persist_history
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


@pytest.mark.asyncio
async def test_wiring_persist_then_load_roundtrip() -> None:
    await persist_history("w1", [_user("hello"), _assistant("hi there")])
    loaded = await load_history("w1")
    assert len(loaded) == 2
    assert isinstance(loaded[0], ModelRequest)
    assert isinstance(loaded[1], ModelResponse)
```

- [x] **Step 9: Run the memory tests**

Run: `uv run pytest tests/test_memory_repository.py -v`
Expected: `5 passed` (4 original + 1 new wiring round-trip).

- [x] **Step 10: Run the whole suite**

Run: `uv run pytest -q`
Expected: `33 passed` (32 + 1 new).

- [x] **Step 11: Commit**

```bash
git add app/agents/memory/ app/features/memory/models.py app/features/memory/repository.py app/features/memory/serialize.py app/core/migrations/env.py tests/conftest.py tests/test_memory_repository.py
git commit -m "refactor: move memory layer under app/agents/memory"
```

---

## Task 5: Run models + in-memory registry

> Status: COMPLETE (committed; events.py pulled in from Task 6 because registry.py imports it; seq starts at 1 per spec §4.5)

**Files:**
- Rewrite: `app/runs/models.py` (full run models; `ErrorBody` unchanged)
- Create: `app/runs/registry.py`
- Modify: `app/core/container.py` (add `runs: RunRegistry`)
- Test: `tests/test_runs_models.py`
- Test: `tests/test_runs_registry.py`

- [x] **Step 1: Write the failing model tests**

Create `tests/test_runs_models.py`:

```python
from __future__ import annotations

from app.runs.models import (
    ErrorBody,
    RunMessage,
    RunRecord,
    RunResponse,
    RunStatus,
    RunStep,
    RunUsage,
)


def test_run_status_values() -> None:
    assert RunStatus.PENDING.value == "pending"
    assert RunStatus.RUNNING.value == "running"
    assert RunStatus.COMPLETED.value == "completed"
    assert RunStatus.FAILED.value == "failed"
    assert RunStatus.CANCELLED.value == "cancelled"


def test_error_body_fields() -> None:
    body = ErrorBody(code="run_not_found", message="nope", details=None, run_id="r1")
    assert body.model_dump() == {
        "code": "run_not_found",
        "message": "nope",
        "details": None,
        "run_id": "r1",
    }


def test_run_message_roles() -> None:
    user = RunMessage(role="user", content="hi")
    assistant = RunMessage(role="assistant", content="yo")
    assert user.role == "user"
    assert assistant.role == "assistant"


def test_run_usage_from_pai() -> None:
    class FakeUsage:
        input_tokens = 10
        output_tokens = 20
        requests = 3

    usage = RunUsage.from_pai(FakeUsage())
    assert usage == RunUsage(input_tokens=10, output_tokens=20, requests=3)


def test_run_record_initial_state() -> None:
    record = RunRecord(run_id="r1", agent="generalist", conversation_id=None)
    assert record.status == RunStatus.PENDING
    assert record.steps == []
    assert record.artifacts == []
    assert record.usage is None
    assert record.error is None
    assert record.seq_counter == 0
    assert record.sse_claimed is False
    assert len(record.events) == 0


def test_run_response_from_record() -> None:
    record = RunRecord(run_id="r1", agent="generalist")
    record.steps.append(
        RunStep(
            index=1,
            type="tool_call",
            name="calculator",
            summary="1+1",
            result="2",
            started_at=record.created_at,
            finished_at=record.created_at,
        )
    )
    response = RunResponse.from_record(record)
    assert response.run_id == "r1"
    assert response.status == RunStatus.PENDING
    assert len(response.steps) == 1
    assert response.steps[0].name == "calculator"
    assert response.error is None
```

- [x] **Step 2: Run the model tests to verify they fail**

Run: `uv run pytest tests/test_runs_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'RunStatus' from 'app.runs.models'`.

- [x] **Step 3: Write the failing registry tests**

Create `tests/test_runs_registry.py`:

```python
from __future__ import annotations

import asyncio

import pytest

from app.runs.events import created_data, done_data
from app.runs.models import RunRecord, RunStatus
from app.runs.registry import (
    CancelConflictError,
    RunNotFoundError,
    RunRegistry,
    SseBusyError,
)


async def _finished_record(registry: RunRegistry, run_id: str) -> RunRecord:
    record = RunRecord(run_id=run_id, agent="generalist")
    registry.register(record)
    await registry.emit(record, "response.created", created_data("generalist", None, "hi"))
    await registry.emit(record, "response.output_text.done", done_data("hi"))
    return record


async def test_emit_assigns_monotonic_sequences() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="seq", agent="generalist")
    registry.register(record)
    event1 = await registry.emit(record, "response.created", created_data("generalist", None, "hi"))
    event2 = await registry.emit(record, "response.output_text.done", done_data("hi"))
    assert event1.sequence == 1
    assert event2.sequence == 2
    assert event2.sequence > event1.sequence
    assert event1.run_id == "seq"


async def test_list_orders_most_recent_first() -> None:
    from datetime import datetime, timedelta, timezone

    registry = RunRegistry()
    record_a = RunRecord(run_id="a", agent="generalist")
    record_b = RunRecord(run_id="b", agent="generalist")
    record_a.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    registry.register(record_a)
    registry.register(record_b)
    runs = await registry.list()
    assert [r.run_id for r in runs] == ["b", "a"]


async def test_get_unknown_raises() -> None:
    registry = RunRegistry()
    with pytest.raises(RunNotFoundError):
        await registry.get("missing")


async def test_cancel_pending_emits_terminal() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="p", agent="generalist")
    registry.register(record)
    cancelled = await registry.cancel("p")
    assert cancelled.status == RunStatus.CANCELLED
    assert cancelled.finished_at is not None
    assert [e.type for e in record.events] == ["run.cancelled"]


async def test_cancel_terminal_raises_conflict() -> None:
    registry = RunRegistry()
    record = await _finished_record(registry, "done")
    record.status = RunStatus.COMPLETED
    with pytest.raises(CancelConflictError):
        await registry.cancel("done")


async def test_claim_subscriber_once_then_busy() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="s", agent="generalist")
    registry.register(record)
    _claimed, replay = await registry.claim_subscriber("s")
    assert replay == []
    with pytest.raises(SseBusyError):
        await registry.claim_subscriber("s")


async def test_wait_for_events_returns_after_emit() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="w", agent="generalist")
    registry.register(record)

    async def waiter() -> list:
        return await registry.wait_for_events(record, timeout=1.0)

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    await registry.emit(record, "response.created", created_data("generalist", None, "hi"))
    events = await task
    assert [e.type for e in events] == ["response.created"]


async def test_claim_subscriber_replays_buffered_events() -> None:
    registry = RunRegistry()
    record = await _finished_record(registry, "r")
    claimed, replay = await registry.claim_subscriber("r")
    assert claimed is record
    assert [e.type for e in replay] == ["response.created", "response.output_text.done"]
```

- [x] **Step 4: Run the registry tests to verify they fail**

Run: `uv run pytest tests/test_runs_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.runs.registry'`.

- [x] **Step 5: Rewrite `app/runs/models.py` with the full run models**

Replace the entire contents of `app/runs/models.py` with:

```python
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.runs.events import RunEvent

EVENT_LOG_MAXLEN = 10_000


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    run_id: str | None = None


class RunStep(BaseModel):
    index: int = 0
    type: Literal["tool_call", "message"]
    name: str
    summary: str
    result: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class RunArtifact(BaseModel):
    name: str
    kind: Literal["text", "structured_output", "error"]
    data: Any = None


class RunUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0

    @classmethod
    def from_pai(cls, usage: Any) -> "RunUsage":
        return cls(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            requests=getattr(usage, "requests", 0) or 0,
        )


class RunMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class RunRecord:
    """Mutable in-memory state for one run.

    All mutations happen under the ``RunRegistry`` lock. ``RunEvent``
    instances live in ``events`` (a bounded deque) for SSE replay.
    """

    def __init__(
        self,
        *,
        run_id: str,
        agent: str,
        conversation_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.agent = agent
        self.conversation_id = conversation_id
        self.metadata: dict | None = None
        self.status: RunStatus = RunStatus.PENDING
        self.created_at: datetime = datetime.now(timezone.utc)
        self.started_at: datetime | None = None
        self.finished_at: datetime | None = None
        self.steps: list[RunStep] = []
        self.artifacts: list[RunArtifact] = []
        self.usage: RunUsage | None = None
        self.error: ErrorBody | None = None
        self.task: asyncio.Task | None = None
        self.events: deque["RunEvent"] = deque(maxlen=EVENT_LOG_MAXLEN)
        self.event_ready: asyncio.Event = asyncio.Event()
        self.seq_counter: int = 0
        self.sse_claimed: bool = False
        self.sse_index: int = 0


class RunResponse(BaseModel):
    run_id: str
    agent: str
    status: RunStatus
    conversation_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[RunStep] = Field(default_factory=list)
    artifacts: list[RunArtifact] = Field(default_factory=list)
    usage: RunUsage | None = None
    error: ErrorBody | None = None

    @classmethod
    def from_record(cls, record: RunRecord) -> "RunResponse":
        return cls(
            run_id=record.run_id,
            agent=record.agent,
            status=record.status,
            conversation_id=record.conversation_id,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            steps=list(record.steps),
            artifacts=list(record.artifacts),
            usage=record.usage,
            error=record.error,
        )
```

- [x] **Step 6: Create `app/runs/registry.py`**

Create `app/runs/registry.py`:

```python
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from app.runs.events import RunEvent, cancelled_data, ping_data, step_data
from app.runs.models import (
    RunRecord,
    RunStatus,
    TERMINAL_STATUSES,
)

SSE_PING_INTERVAL = 15.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunNotFoundError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} does not exist")
        self.run_id = run_id


class CancelConflictError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} is already terminal")
        self.run_id = run_id


class SseBusyError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} already has an SSE subscriber")
        self.run_id = run_id


class RunRegistry:
    """In-memory run registry. All mutations happen under a single lock."""

    def __init__(self) -> None:
        self._records: dict[str, RunRecord] = {}
        self.lock = asyncio.Lock()

    def register(self, record: RunRecord) -> None:
        """Insert a pre-built record (tests and direct callers)."""
        self._records[record.run_id] = record

    async def create(self, request: Any, container: Any) -> RunRecord:
        """Create a pending run and schedule its background task."""
        record = RunRecord(
            run_id=uuid.uuid4().hex,
            agent=request.agent,
            conversation_id=request.conversation_id,
        )
        record.metadata = request.metadata
        async with self.lock:
            self._records[record.run_id] = record
        from app.runs.runner import execute_run  # local import avoids a cycle

        task = asyncio.create_task(execute_run(record, self, container, request))
        record.task = task
        return record

    async def get(self, run_id: str) -> RunRecord:
        async with self.lock:
            record = self._records.get(run_id)
        if record is None:
            raise RunNotFoundError(run_id)
        return record

    async def list(self) -> list[RunRecord]:
        async with self.lock:
            return sorted(
                self._records.values(),
                key=lambda r: r.created_at,
                reverse=True,
            )

    async def cancel(self, run_id: str) -> RunRecord:
        """Transition to ``cancelled`` and cancel the run's task (§5.3)."""
        async with self.lock:
            record = self._records.get(run_id)
            if record is None:
                raise RunNotFoundError(run_id)
            if record.status in TERMINAL_STATUSES:
                raise CancelConflictError(run_id)
            was_running = record.status == RunStatus.RUNNING
            record.status = RunStatus.CANCELLED
            record.finished_at = _now()
            task = record.task
            if not was_running:
                # Task never started: no runner to emit the terminal event.
                self._emit_locked(record, "run.cancelled", cancelled_data())
        if task is not None:
            task.cancel()
        return record

    async def shutdown(self) -> None:
        """Cancel every in-flight run task (app shutdown)."""
        async with self.lock:
            tasks = [
                record.task
                for record in self._records.values()
                if record.task is not None and not record.task.done()
            ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------ #
    # Event log
    # ------------------------------------------------------------------ #

    async def emit(
        self, record: RunRecord, event_type: str, data: dict[str, Any]
    ) -> RunEvent:
        async with self.lock:
            return self._emit_locked(record, event_type, data)

    def _emit_locked(
        self, record: RunRecord, event_type: str, data: dict[str, Any]
    ) -> RunEvent:
        sequence = record.seq_counter
        record.seq_counter += 1
        event = RunEvent(
            type=event_type,
            run_id=record.run_id,
            sequence=sequence,
            created_at=_now(),
            data=data,
        )
        self._append_event(record, event)
        record.event_ready.set()
        return event

    def _append_event(self, record: RunRecord, event: RunEvent) -> None:
        log = record.events
        if event.terminal:
            while len(log) >= log.maxlen and not log[0].terminal:
                log.popleft()
        elif len(log) >= log.maxlen:
            log.popleft()
        log.append(event)

    async def add_step(self, record: RunRecord, step: Any) -> None:
        """Append a step to the record and emit its ``run.step`` event."""
        async with self.lock:
            step.index = len(record.steps) + 1
            record.steps.append(step)
            self._emit_locked(record, "run.step", step_data(step))

    async def emit_ping(self, record: RunRecord) -> RunEvent:
        """Build a keepalive ping event (not stored in the event log)."""
        async with self.lock:
            sequence = record.seq_counter
            record.seq_counter += 1
            return RunEvent(
                type="ping",
                run_id=record.run_id,
                sequence=sequence,
                created_at=_now(),
                data=ping_data(),
            )

    # ------------------------------------------------------------------ #
    # SSE subscriber contract (§4.5/§9.9): one subscriber, one-shot claim.
    # ------------------------------------------------------------------ #

    async def claim_subscriber(
        self, run_id: str
    ) -> tuple[RunRecord, list[RunEvent]]:
        """Claim the single SSE subscriber slot; returns buffered events."""
        async with self.lock:
            record = self._records.get(run_id)
            if record is None:
                raise RunNotFoundError(run_id)
            if record.sse_claimed:
                raise SseBusyError(run_id)
            record.sse_claimed = True
            record.sse_index = len(record.events)
            replay = list(record.events)
        return record, replay

    async def wait_for_events(
        self, record: RunRecord, timeout: float
    ) -> list[RunEvent]:
        """Wait up to ``timeout`` for new events; return them (or [] on timeout)."""
        async with self.lock:
            new = self._new_events(record)
            if new:
                return new
            record.event_ready.clear()
        try:
            await asyncio.wait_for(record.event_ready.wait(), timeout=timeout)
        except TimeoutError:
            return []
        async with self.lock:
            return self._new_events(record)

    def _new_events(self, record: RunRecord) -> list[RunEvent]:
        index = record.sse_index
        events = list(record.events)[index:]
        if events:
            record.sse_index = index + len(events)
        return events

    def release_subscriber(self, record: RunRecord) -> None:
        """Called when the SSE generator ends.

        The claim is one-shot: ``sse_claimed`` stays set so later subscribers
        are rejected with ``409 sse_busy``; clients must poll for state.
        """
        return None
```

- [x] **Step 7: Add the run registry to the container**

In `app/core/container.py`, make these three edits:

Edit 1 — imports:

```python
from app.agents.registry import AgentRegistry, load_agent_registry
from app.core.config import Settings
from app.core.model import get_model
from app.core.prompts import PromptEngine
from app.runs.registry import RunRegistry
```

Edit 2 — dataclass fields:

```python
@dataclass
class AppContainer:
    """Root container holding process-wide singletons."""

    config: Settings
    model: OpenAIChatModel
    prompts: PromptEngine
    agents: AgentRegistry
    runs: RunRegistry
```

Edit 3 — `build_container` body:

```python
def build_container(config: Settings | None = None) -> AppContainer:
    """Construct and cache every application-scoped singleton."""
    global _container
    resolved = config or Settings()
    container = AppContainer(
        config=resolved,
        model=get_model(),
        prompts=PromptEngine(),
        agents=load_agent_registry(),
        runs=RunRegistry(),
    )
    _container = container
    return container
```

- [x] **Step 8: Run the new tests**

Run: `uv run pytest tests/test_runs_models.py tests/test_runs_registry.py -v`
Expected: `14 passed` (6 models + 8 registry).

- [x] **Step 9: Run the whole suite**

Run: `uv run pytest -q`
Expected: `47 passed` (33 + 14 new).

- [x] **Step 10: Commit**

```bash
git add app/runs/models.py app/runs/registry.py app/core/container.py tests/test_runs_models.py tests/test_runs_registry.py
git commit -m "feat: add run models and in-memory run registry"
```

---

## Task 6: Run runner + events + timeout config

> Status: COMPLETE (committed; events.py already created in Task 5; `test_runner_completes_string_run` sets `agent_model(TestModel(call_tools=[], ...))` since a plain TestModel calls all tools with junk args; memory helpers guard the None conversation_id)

**Files:**
- Modify: `app/core/config.py` (add `RUN_TIMEOUT_SECONDS`)
- Modify: `.env.example` (add `RUN_TIMEOUT_SECONDS`)
- Create: `app/runs/events.py`
- Create: `app/runs/runner.py`
- Test: `tests/test_runs_runner.py`

- [x] **Step 1: Write the failing tests**

Create `tests/test_runs_runner.py`:

```python
from __future__ import annotations

import asyncio
import types
from datetime import datetime, timezone

import pytest

from app.core.container import get_container
from app.runs.events import (
    RunEvent,
    cancelled_data,
    completed_data,
    created_data,
    delta_data,
    done_data,
    failed_data,
    ping_data,
    step_data,
)
from app.runs.models import (
    ErrorBody,
    RunArtifact,
    RunMessage,
    RunRecord,
    RunStatus,
    RunStep,
    RunUsage,
)
from app.runs.registry import RunRegistry
from app.runs.runner import execute_run, run_messages_to_model_messages


def _request(**overrides: object) -> types.SimpleNamespace:
    """Duck-typed stand-in for ``app.api.runs.CreateRunRequest``."""
    defaults = {
        "agent": "generalist",
        "input": "hello",
        "conversation_id": None,
        "message_history": None,
        "tools": None,
        "capabilities": None,
        "max_steps": 8,
        "metadata": None,
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_event_data_builders() -> None:
    assert created_data("generalist", "c1", "hi") == {
        "agent": "generalist",
        "conversation_id": "c1",
        "input": "hi",
    }
    assert delta_data("Hi") == {"delta": "Hi"}
    assert done_data("Hi") == {"text": "Hi"}
    assert cancelled_data() == {"error": None}
    assert "t" in ping_data()

    step = RunStep(
        index=1,
        type="tool_call",
        name="calculator",
        summary="1+1",
        result="2",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    assert step_data(step) == {"step": step.model_dump(mode="json")}

    error = ErrorBody(code="model_error", message="boom", details=None, run_id="r")
    assert failed_data(error)["error"]["code"] == "model_error"

    usage = RunUsage(input_tokens=1, output_tokens=2, requests=3)
    artifacts = [RunArtifact(name="output", kind="text", data="hi")]
    data = completed_data("completed", usage, artifacts)
    assert data["status"] == "completed"
    assert data["usage"]["requests"] == 3
    assert data["artifacts"][0]["data"] == "hi"


def test_run_event_terminal() -> None:
    terminal = RunEvent(
        type="response.completed",
        run_id="r",
        sequence=1,
        created_at=datetime.now(timezone.utc),
        data={},
    )
    assert terminal.terminal
    delta = RunEvent(
        type="response.output_text.delta",
        run_id="r",
        sequence=2,
        created_at=datetime.now(timezone.utc),
        data={},
    )
    assert not delta.terminal
    assert RunEvent(
        type="response.failed",
        run_id="r",
        sequence=3,
        created_at=datetime.now(timezone.utc),
        data={},
    ).terminal
    assert RunEvent(
        type="run.cancelled",
        run_id="r",
        sequence=4,
        created_at=datetime.now(timezone.utc),
        data={},
    ).terminal


def test_run_messages_conversion() -> None:
    converted = run_messages_to_model_messages(
        [
            RunMessage(role="user", content="hi"),
            RunMessage(role="assistant", content="yo"),
        ]
    )
    assert len(converted) == 2
    assert type(converted[0]).__name__ == "ModelRequest"
    assert type(converted[1]).__name__ == "ModelResponse"


async def test_runner_completes_string_run() -> None:
    container = get_container()
    request = _request(agent="generalist", input="hello")
    registry = RunRegistry()
    record = await registry.create(request, container)
    assert record.task is not None
    await record.task
    assert record.status == RunStatus.COMPLETED
    assert record.started_at is not None
    assert record.finished_at is not None
    assert record.artifacts[0].kind == "text"
    assert record.usage is not None and record.usage.requests >= 1
    types = [e.type for e in record.events]
    assert types[0] == "response.created"
    assert types[-1] == "response.completed"
    assert "response.output_text.delta" in types
    assert "response.output_text.done" in types


async def test_runner_extractor_structured_artifact() -> None:
    container = get_container()
    request = _request(agent="extractor", input="Satya Nadella runs Microsoft.")
    registry = RunRegistry()
    record = await registry.create(request, container)
    await record.task
    assert record.status == RunStatus.COMPLETED
    artifact = record.artifacts[0]
    assert artifact.kind == "structured_output"
    dumped = artifact.data.model_dump()  # type: ignore[attr-defined]
    assert set(dumped) >= {"entities", "language", "summary"}


async def test_runner_timeout_fails_run(monkeypatch, agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    from app.core.config import settings

    monkeypatch.setattr(settings, "run_timeout_seconds", 0.05)
    container = get_container()

    async def slow_fetch(url: str, *, timeout: float = 10.0) -> str:
        await asyncio.sleep(0.5)
        return "slow-body"

    monkeypatch.setitem(container.agents.tools, "fetch", slow_fetch)
    agent_model(
        ScriptedTestModel(
            call_tools=["fetch"],
            tool_args={"fetch": {"url": "http://example.com"}},
            custom_output_text="done",
        )
    )
    request = _request(agent="generalist", input="fetch something")
    registry = RunRegistry()
    record = await registry.create(request, container)
    await asyncio.gather(record.task, return_exceptions=True)
    assert record.status == RunStatus.FAILED
    assert record.error is not None
    assert record.error.code == "timeout"
    assert record.events[-1].type == "response.failed"


async def test_runner_tool_error_after_retries(monkeypatch, agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    container = get_container()

    def always_fail(x: str) -> str:
        raise ValueError("nope")

    monkeypatch.setitem(container.agents.tools, "calculator", always_fail)
    agent_model(
        ScriptedTestModel(
            call_tools=["calculator"],
            tool_args={"calculator": {"expression": "1+1"}},
            custom_output_text="x",
        )
    )
    request = _request(agent="generalist", input="compute")
    registry = RunRegistry()
    record = await registry.create(request, container)
    await record.task
    assert record.status == RunStatus.FAILED
    assert record.error is not None
    assert record.error.code == "tool_error"
    assert record.events[-1].type == "response.failed"


async def test_runner_cancel_mid_run(monkeypatch, agent_model) -> None:
    from tests.conftest import ScriptedTestModel

    container = get_container()

    async def slow_fetch(url: str, *, timeout: float = 10.0) -> str:
        await asyncio.sleep(0.5)
        return "slow-body"

    monkeypatch.setitem(container.agents.tools, "fetch", slow_fetch)
    agent_model(
        ScriptedTestModel(
            call_tools=["fetch"],
            tool_args={"fetch": {"url": "http://example.com"}},
            custom_output_text="done",
        )
    )
    request = _request(agent="generalist", input="fetch something")
    registry = RunRegistry()
    record = await registry.create(request, container)
    for _ in range(50):
        if record.status == RunStatus.RUNNING:
            break
        await asyncio.sleep(0.01)
    assert record.status == RunStatus.RUNNING
    cancelled = await registry.cancel(record.run_id)
    assert cancelled.status == RunStatus.CANCELLED
    await asyncio.gather(record.task, return_exceptions=True)
    assert record.status == RunStatus.CANCELLED
    assert record.events[-1].type == "run.cancelled"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_runs_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.runs.runner'`.

- [x] **Step 3: Add the timeout setting**

In `app/core/config.py`, after the CORS block and before the `@field_validator` decorator, add:

```python
    # Runs: wall-clock budget for a single run (seconds).
    run_timeout_seconds: int = Field(default=300, alias="RUN_TIMEOUT_SECONDS")
```

In `.env.example`, after the `CORS_ORIGINS` line, add:

```
RUN_TIMEOUT_SECONDS=300
```

- [x] **Step 4: Create `app/runs/events.py`**

Create `app/runs/events.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.runs.models import ErrorBody, RunArtifact, RunStep, RunUsage

TERMINAL_EVENT_TYPES = frozenset(
    {"response.completed", "response.failed", "run.cancelled"}
)


class RunEvent(BaseModel):
    type: str
    run_id: str
    sequence: int
    created_at: datetime
    data: dict[str, Any]

    @property
    def terminal(self) -> bool:
        return self.type in TERMINAL_EVENT_TYPES


def created_data(
    agent: str, conversation_id: str | None, input_text: str
) -> dict[str, Any]:
    return {"agent": agent, "conversation_id": conversation_id, "input": input_text}


def delta_data(delta: str) -> dict[str, Any]:
    return {"delta": delta}


def done_data(text: str) -> dict[str, Any]:
    return {"text": text}


def step_data(step: RunStep) -> dict[str, Any]:
    return {"step": step.model_dump(mode="json")}


def completed_data(
    status: str, usage: RunUsage | None, artifacts: list[RunArtifact]
) -> dict[str, Any]:
    return {
        "status": status,
        "usage": usage.model_dump(mode="json") if usage else {},
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
    }


def failed_data(error: ErrorBody) -> dict[str, Any]:
    return {"error": error.model_dump(mode="json")}


def cancelled_data() -> dict[str, Any]:
    return {"error": None}


def ping_data() -> dict[str, Any]:
    return {"t": datetime.now(timezone.utc).isoformat()}
```

- [x] **Step 5: Create `app/runs/runner.py`**

Create `app/runs/runner.py`:

```python
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic_ai import UsageLimits
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartEndEvent,
    TextPart,
)

from app.agents.memory.repository import MemoryRepository
from app.core.config import settings
from app.core.db import get_session_maker
from app.runs.events import (
    cancelled_data,
    completed_data,
    created_data,
    delta_data,
    done_data,
    failed_data,
)
from app.runs.models import (
    ErrorBody,
    RunArtifact,
    RunMessage,
    RunRecord,
    RunStatus,
    RunStep,
    RunUsage,
    TERMINAL_STATUSES,
)

if TYPE_CHECKING:
    from app.runs.registry import RunRegistry


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def usage_limits(max_steps: int) -> UsageLimits:
    return UsageLimits(
        request_limit=max(2, max_steps * 3),
        tool_calls_limit=max(1, max_steps),
    )


def run_messages_to_model_messages(messages: list[RunMessage]) -> list[Any]:
    """Convert API ``RunMessage`` DTOs into pydantic-ai ``ModelMessage``s."""
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    converted: list[Any] = []
    for message in messages:
        if message.role == "user":
            converted.append(
                ModelRequest(
                    parts=[
                        UserPromptPart(content=message.content, timestamp=now_utc())
                    ]
                )
            )
        else:
            converted.append(ModelResponse(parts=[TextPart(content=message.content)]))
    return converted


def classify_error(exc: Exception) -> tuple[str, str]:
    from pydantic_ai.exceptions import ToolRetryError

    message = str(exc) or exc.__class__.__name__
    if isinstance(exc, ToolRetryError) or (
        "exceeded max retries count" in message and "Tool" in message
    ):
        return "tool_error", f"tool call failed after retries: {message}"
    return "model_error", message


def make_step_handler(
    record: RunRecord, registry: Any, *, emit_message_steps: bool
) -> Any:
    """Build the ``event_stream_handler`` that records ``run.step`` events."""
    pending: dict[str, dict[str, Any]] = {}

    async def handler(_ctx: Any, events: AsyncIterable[Any]) -> None:
        async for event in events:
            if isinstance(event, FunctionToolCallEvent):
                args = event.part.args_as_dict() if event.part.args else {}
                pending[event.tool_call_id] = {
                    "name": event.part.tool_name,
                    "summary": json.dumps(args, default=str)[:200],
                    "started_at": now_utc(),
                }
            elif isinstance(event, FunctionToolResultEvent):
                info = pending.pop(event.tool_call_id, None)
                if info is not None:
                    await registry.add_step(
                        record,
                        RunStep(
                            index=0,
                            type="tool_call",
                            name=info["name"],
                            summary=info["summary"],
                            result=str(event.part.content)[:500],
                            started_at=info["started_at"],
                            finished_at=now_utc(),
                        ),
                    )
            elif (
                emit_message_steps
                and isinstance(event, PartEndEvent)
                and isinstance(event.part, TextPart)
            ):
                await registry.add_step(
                    record,
                    RunStep(
                        index=0,
                        type="message",
                        name="message",
                        summary=event.part.content[:200],
                        result=None,
                        started_at=now_utc(),
                        finished_at=now_utc(),
                    ),
                )

    return handler


async def execute_run(
    record: RunRecord, registry: "RunRegistry", container: Any, request: Any
) -> None:
    """The asyncio task body for a single run (§8.1)."""
    definition = container.agents.definitions[request.agent]

    async with registry.lock:
        if record.status == RunStatus.CANCELLED:
            return  # cancelled before the task started; cancel() emitted the terminal event
        if definition.uses_memory and record.conversation_id is None:
            record.conversation_id = uuid.uuid4().hex
        record.status = RunStatus.RUNNING
        record.started_at = now_utc()

    await registry.emit(
        record,
        "response.created",
        created_data(record.agent, record.conversation_id, request.input),
    )

    try:
        await _execute_agent(record, registry, container, request, definition)
    except asyncio.CancelledError:
        pass  # a cancel request raced us; the finally block emits run.cancelled
    except TimeoutError:
        error = ErrorBody(
            code="timeout",
            message="run exceeded RUN_TIMEOUT_SECONDS",
            details=None,
            run_id=record.run_id,
        )
        await _fail(record, registry, error)
    except Exception as exc:  # noqa: BLE001 - run-level errors are recorded, not raised
        code, message = classify_error(exc)
        error = ErrorBody(
            code=code, message=message, details=None, run_id=record.run_id
        )
        await _fail(record, registry, error)
    finally:
        async with registry.lock:
            if record.status == RunStatus.CANCELLED:
                # The run was cancelled mid-flight; no terminal event yet.
                registry._emit_locked(record, "run.cancelled", cancelled_data())
            record.task = None


async def _execute_agent(
    record: RunRecord,
    registry: "RunRegistry",
    container: Any,
    request: Any,
    definition: Any,
) -> None:
    agent = container.agents.build_agent(
        request.agent,
        tools=request.tools,
        capabilities=request.capabilities,
    )

    history: list[Any] | None = None
    if definition.uses_memory:
        history = await _load_history(record.conversation_id)
    if request.message_history:
        history = run_messages_to_model_messages(request.message_history)

    step_handler = make_step_handler(
        record,
        registry,
        emit_message_steps=(definition.output_type == "structured_output"),
    )

    if definition.output_type == "string":
        text = ""
        all_messages: list[Any] = []
        usage: RunUsage | None = None
        async with asyncio.timeout(settings.run_timeout_seconds):
            async with agent:
                async with agent.run_stream(
                    request.input,
                    message_history=history or None,
                    usage_limits=usage_limits(request.max_steps),
                    event_stream_handler=step_handler,
                ) as stream:
                    async for delta in stream.stream_text():
                        text += delta
                        await registry.emit(
                            record, "response.output_text.delta", delta_data(delta)
                        )
                    await registry.emit(
                        record, "response.output_text.done", done_data(text)
                    )
                    all_messages = list(stream.all_messages())
                    usage = RunUsage.from_pai(stream.usage)
        artifact = RunArtifact(name="output", kind="text", data=text)
    else:
        all_messages = []
        usage = None
        async with asyncio.timeout(settings.run_timeout_seconds):
            async with agent:
                result = await agent.run(
                    request.input,
                    message_history=history or None,
                    usage_limits=usage_limits(request.max_steps),
                    event_stream_handler=step_handler,
                )
        all_messages = list(result.all_messages())
        usage = RunUsage.from_pai(result.usage)
        artifact = RunArtifact(
            name="output", kind="structured_output", data=result.output
        )

    if definition.uses_memory:
        await _persist_history(record.conversation_id, all_messages)
    await _complete(record, registry, [artifact], usage)


async def _complete(
    record: RunRecord,
    registry: "RunRegistry",
    artifacts: list[RunArtifact],
    usage: RunUsage | None,
) -> None:
    async with registry.lock:
        if record.status in TERMINAL_STATUSES:
            return
        record.status = RunStatus.COMPLETED
        record.finished_at = now_utc()
        record.artifacts = artifacts
        record.usage = usage
        registry._emit_locked(
            record,
            "response.completed",
            completed_data(record.status.value, usage, artifacts),
        )


async def _fail(
    record: RunRecord, registry: "RunRegistry", error: ErrorBody
) -> None:
    async with registry.lock:
        if record.status in TERMINAL_STATUSES:
            return
        record.status = RunStatus.FAILED
        record.finished_at = now_utc()
        record.error = error
        registry._emit_locked(record, "response.failed", failed_data(error))


async def _load_history(conversation_id: str | None) -> list[Any]:
    session = get_session_maker()()
    try:
        return await MemoryRepository(session).get(conversation_id)
    finally:
        await session.close()


async def _persist_history(conversation_id: str | None, messages: list[Any]) -> None:
    session = get_session_maker()()
    try:
        await MemoryRepository(session).set(conversation_id, messages)
        await session.commit()
    finally:
        await session.close()
```

- [x] **Step 6: Run the tests**

Run: `uv run pytest tests/test_runs_runner.py -v`
Expected: `8 passed`.

- [x] **Step 7: Run the whole suite**

Run: `uv run pytest -q`
Expected: `55 passed` (47 + 8 new).

- [x] **Step 8: Commit**

```bash
git add app/core/config.py .env.example app/runs/events.py app/runs/runner.py tests/test_runs_runner.py
git commit -m "feat: add run runner with lifecycle, events, timeout, and cancel handling"
```

---

## Task 7: SSE event stream layer

> Status: COMPLETE (committed; `test_stream_waits_for_late_events` expectation corrected to include the replayed `response.created`, per the spec's replay guarantee)

**Files:**
- Create: `app/runs/sse.py`
- Test: `tests/test_sse.py`

- [x] **Step 1: Write the failing tests**

Create `tests/test_sse.py`:

```python
from __future__ import annotations

import asyncio

from app.runs.events import RunEvent, completed_data, created_data, done_data
from app.runs.models import RunRecord
from app.runs.registry import RunRegistry
from app.runs.sse import event_frame, stream_events


def test_event_frame_format() -> None:
    from datetime import datetime, timezone

    event = RunEvent(
        type="response.created",
        run_id="r",
        sequence=1,
        created_at=datetime.now(timezone.utc),
        data={},
    )
    frame = event_frame(event)
    assert frame == {"event": "response.created", "data": event.model_dump_json()}


async def test_stream_replays_buffered_events() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="r1", agent="generalist")
    registry.register(record)
    await registry.emit(record, "response.created", created_data("generalist", None, "hi"))
    await registry.emit(record, "response.output_text.done", done_data("hi"))
    await registry.emit(record, "response.completed", completed_data("completed", None, []))

    _claimed, replay = await registry.claim_subscriber("r1")
    frames = [frame async for frame in stream_events(record, registry, replay)]
    events = [frame["event"] for frame in frames]
    assert events == [
        "response.created",
        "response.output_text.done",
        "response.completed",
    ]


async def test_stream_waits_for_late_events() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="r2", agent="generalist")
    registry.register(record)
    await registry.emit(record, "response.created", created_data("generalist", None, "hi"))

    async def consume() -> list:
        _claimed, replay = await registry.claim_subscriber("r2")
        frames = []
        async for frame in stream_events(record, registry, replay):
            frames.append(frame)
        return frames

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await registry.emit(record, "response.output_text.done", done_data("done"))
    await registry.emit(record, "response.completed", completed_data("completed", None, []))
    frames = await task
    events = [frame["event"] for frame in frames]
    assert events == ["response.output_text.done", "response.completed"]


async def test_stream_emits_ping_while_running() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="r3", agent="generalist")
    registry.register(record)
    await registry.emit(record, "response.created", created_data("generalist", None, "hi"))

    async def consume() -> list:
        _claimed, replay = await registry.claim_subscriber("r3")
        frames = []
        async for frame in stream_events(record, registry, replay, ping_interval=0.05):
            frames.append(frame)
            if len(frames) == 2:
                break
        return frames

    frames = await consume()
    events = [frame["event"] for frame in frames]
    assert events[0] == "response.created"
    assert events[1] == "ping"
    assert "t" in frames[1]["data"]


async def test_stream_does_not_ping_after_terminal() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="r4", agent="generalist")
    registry.register(record)
    await registry.emit(record, "response.created", created_data("generalist", None, "hi"))
    await registry.emit(record, "response.completed", completed_data("completed", None, []))

    _claimed, replay = await registry.claim_subscriber("r4")
    frames = [
        frame
        async for frame in stream_events(record, registry, replay, ping_interval=0.02)
    ]
    assert frames[-1]["event"] == "response.completed"
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.runs.sse'`.

- [x] **Step 3: Create `app/runs/sse.py`**

Create `app/runs/sse.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator

from app.runs.events import RunEvent
from app.runs.models import RunRecord, TERMINAL_STATUSES
from app.runs.registry import RunRegistry, SSE_PING_INTERVAL


def event_frame(event: RunEvent) -> dict[str, str]:
    """sse-starlette frame dict for a run event."""
    return {"event": event.type, "data": event.model_dump_json()}


async def stream_events(
    record: RunRecord,
    registry: RunRegistry,
    replay: list[RunEvent],
    *,
    ping_interval: float = SSE_PING_INTERVAL,
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE frames for a run; the terminal event is always last."""
    try:
        for event in replay:
            yield event_frame(event)
            if event.terminal:
                return
        while True:
            new_events = await registry.wait_for_events(record, ping_interval)
            if new_events:
                for event in new_events:
                    yield event_frame(event)
                    if event.terminal:
                        return
            elif record.status not in TERMINAL_STATUSES:
                ping = await registry.emit_ping(record)
                yield event_frame(ping)
    finally:
        registry.release_subscriber(record)
```

- [x] **Step 4: Run the tests**

Run: `uv run pytest tests/test_sse.py -v`
Expected: `5 passed`.

- [x] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: `60 passed` (55 + 5 new).

- [x] **Step 6: Commit**

```bash
git add app/runs/sse.py tests/test_sse.py
git commit -m "feat: add SSE event stream layer"
```

---

## Task 8: HTTP routers (runs + agents) and app wiring

> Status: COMPLETE (committed; deviations: test SQLite moved from `:memory:` to a temp file because run-task cancellation invalidates the aiosqlite connection and would destroy the in-memory DB; conftest default `TestModel` uses `call_tools=[]` and memory-run tests set `call_tools=[]` because a plain TestModel calls all generalist tools with junk args and fails the run)

**Files:**
- Create: `app/api/runs.py`
- Create: `app/api/agents.py`
- Modify: `app/api/router.py` (include new routers; keep legacy routers until Task 10)
- Modify: `app/main.py` (error handlers, lifespan run shutdown, description)
- Create: `tests/test_runs.py`
- Create: `tests/test_runs_cancel.py`
- Create: `tests/test_runs_events.py`
- Create: `tests/test_agents.py`
- Create: `tests/test_extractor.py`
- Create: `tests/test_memory_runs.py`
- Modify: `tests/test_error_envelope.py` (add integration tests against the real app)

- [x] **Step 1: Write the failing endpoint tests**

Create `tests/test_runs.py`:

```python
from __future__ import annotations

import time

from tests.conftest import wait_for_status


def test_create_run_returns_202_pending(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hello"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "pending"
    assert body["run_id"]
    assert body["conversation_id"] is None
    assert body["steps"] == []
    assert body["artifacts"] == []
    assert body["usage"] is None
    assert body["error"] is None


def test_create_run_unknown_agent(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "nope", "input": "hi"})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "unknown_agent"
    assert "nope" in error["message"]


def test_create_run_validation_error(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": ""})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation_error"
    assert any(e["loc"] == ["body", "input"] for e in error["details"])


def test_max_steps_bounds_rejected(client) -> None:
    r = client.post(
        "/api/v1/runs", json={"agent": "generalist", "input": "hi", "max_steps": 21}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_run_lifecycle_to_completed(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hello"})
    run_id = r.json()["run_id"]
    body = wait_for_status(client, run_id, "completed")
    assert body["status"] == "completed"
    assert body["artifacts"][0]["kind"] == "text"
    assert body["usage"]["requests"] >= 1
    assert body["started_at"] is not None
    assert body["finished_at"] is not None


def test_list_runs_most_recent_first(client) -> None:
    r1 = client.post("/api/v1/runs", json={"agent": "generalist", "input": "one"})
    time.sleep(0.05)
    r2 = client.post("/api/v1/runs", json={"agent": "generalist", "input": "two"})
    resp = client.get("/api/v1/runs")
    assert resp.status_code == 200
    runs = resp.json()
    ids = [run["run_id"] for run in runs]
    assert ids[0] == r2.json()["run_id"]
    assert ids[1] == r1.json()["run_id"]


def test_get_run_404(client) -> None:
    r = client.get("/api/v1/runs/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "run_not_found"
```

- [x] **Step 2: Write the cancel tests**

Create `tests/test_runs_cancel.py`:

```python
from __future__ import annotations

import asyncio

from tests.conftest import ScriptedTestModel, wait_for_status


def test_cancel_pending_run_unit() -> None:
    from app.runs.models import RunRecord, RunStatus
    from app.runs.registry import RunRegistry

    async def go() -> None:
        registry = RunRegistry()
        record = RunRecord(run_id="r-pending", agent="generalist")
        registry.register(record)
        cancelled = await registry.cancel("r-pending")
        assert cancelled.status == RunStatus.CANCELLED
        assert [e.type for e in record.events] == ["run.cancelled"]

    asyncio.run(go())


def test_cancel_running_run_via_api(client, agent_model) -> None:
    async def slow_fetch(url: str, *, timeout: float = 10.0) -> str:
        await asyncio.sleep(0.5)
        return "slow-body"

    container = client.app.state.container
    container.agents.tools["fetch"] = slow_fetch
    agent_model(
        ScriptedTestModel(
            call_tools=["fetch"],
            tool_args={"fetch": {"url": "http://example.com"}},
            custom_output_text="done",
        )
    )
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "fetch it"})
    run_id = r.json()["run_id"]
    body = wait_for_status(client, run_id, "running", timeout=2.0)
    assert body["status"] == "running"

    c = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert c.status_code == 202
    assert c.json()["status"] == "cancelled"

    final = wait_for_status(client, run_id, "cancelled", timeout=2.0)
    assert final["finished_at"] is not None

    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        lines = [ln for ln in resp.iter_lines() if ln]
    assert any("event: run.cancelled" in ln for ln in lines)


def test_cancel_completed_run_conflict(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hi"})
    run_id = r.json()["run_id"]
    wait_for_status(client, run_id, "completed")
    c = client.post(f"/api/v1/runs/{run_id}/cancel")
    assert c.status_code == 409
    assert c.json()["error"]["code"] == "cancel_conflict"


def test_cancel_unknown_run_404(client) -> None:
    c = client.post("/api/v1/runs/nope/cancel")
    assert c.status_code == 404
    assert c.json()["error"]["code"] == "run_not_found"
```

- [x] **Step 3: Write the SSE endpoint tests**

Create `tests/test_runs_events.py`:

```python
from __future__ import annotations

import json

from tests.conftest import ScriptedTestModel, wait_for_status


def _parse_frames(lines: list[str]) -> list[dict]:
    frames = []
    current = None
    for line in lines:
        if line.startswith("event:"):
            current = {"event": line.split(":", 1)[1].strip()}
        elif line.startswith("data:") and current is not None:
            current["data"] = json.loads(line.split(":", 1)[1].strip())
            frames.append(current)
            current = None
    return frames


def test_generalist_stream_envelope_and_order(client, agent_model) -> None:
    agent_model(
        ScriptedTestModel(
            call_tools=["calculator"],
            tool_args={"calculator": {"expression": "1+1"}},
            custom_output_text="The result is 2.",
        )
    )
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "compute 1+1"})
    run_id = r.json()["run_id"]
    wait_for_status(client, run_id, "completed")

    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        lines = [ln for ln in resp.iter_lines() if ln]

    frames = _parse_frames(lines)
    types = [f["event"] for f in frames]
    assert types[0] == "response.created"
    assert types[-1] == "response.completed"
    sequences = [f["data"]["sequence"] for f in frames]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert any(
        f["event"] == "run.step" and f["data"]["data"]["step"]["name"] == "calculator"
        for f in frames
    )
    delta_idx = types.index("response.output_text.delta")
    done_idx = types.index("response.output_text.done")
    assert delta_idx < done_idx < len(types) - 1


def test_extractor_stream_has_no_text_events(client) -> None:
    r = client.post(
        "/api/v1/runs",
        json={"agent": "extractor", "input": "Satya Nadella runs Microsoft."},
    )
    run_id = r.json()["run_id"]
    wait_for_status(client, run_id, "completed")

    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as resp:
        lines = [ln for ln in resp.iter_lines() if ln]

    frames = _parse_frames(lines)
    types = [f["event"] for f in frames]
    assert types == ["response.created", "response.completed"]
    artifact = frames[-1]["data"]["data"]["artifacts"][0]
    assert artifact["kind"] == "structured_output"


def test_stream_unknown_run_404(client) -> None:
    r = client.get("/api/v1/runs/nope/events")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "run_not_found"


def test_second_subscriber_rejected(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hi"})
    run_id = r.json()["run_id"]
    wait_for_status(client, run_id, "completed")

    with client.stream("GET", f"/api/v1/runs/{run_id}/events") as resp:
        lines = [ln for ln in resp.iter_lines() if ln]
    assert any("response.completed" in ln for ln in lines)

    # The claim is one-shot: a later subscriber is rejected with 409.
    r2 = client.get(f"/api/v1/runs/{run_id}/events")
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "sse_busy"
```

- [x] **Step 4: Write the agent-discovery tests**

Create `tests/test_agents.py`:

```python
from __future__ import annotations


def test_list_agents(client) -> None:
    r = client.get("/api/v1/agents")
    assert r.status_code == 200
    names = {a["name"] for a in r.json()}
    assert names == {"generalist", "extractor"}


def test_get_generalist_spec(client) -> None:
    r = client.get("/api/v1/agents/generalist")
    assert r.status_code == 200
    spec = r.json()
    assert spec["name"] == "generalist"
    assert spec["output_type"] == "string"
    assert "calculator" in spec["tools"]
    assert "delegate_skill" in spec["tools"]
    assert spec["capabilities"] == ["thinking"]
    assert spec["uses_memory"] is True
    assert spec["instructions_key"] == "generalist"
    assert spec["default_max_steps"] == 8


def test_get_extractor_schema(client) -> None:
    r = client.get("/api/v1/agents/extractor")
    assert r.status_code == 200
    spec = r.json()
    assert spec["output_type"] == "structured_output"
    assert spec["output_schema"]["title"] == "ExtractionResult"
    assert spec["uses_memory"] is False
    assert spec["tools"] == []


def test_get_agent_404(client) -> None:
    r = client.get("/api/v1/agents/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "agent_not_found"
```

- [x] **Step 5: Write the extractor test**

Create `tests/test_extractor.py`:

```python
from __future__ import annotations

from tests.conftest import wait_for_status


def test_extractor_structured_artifact(client) -> None:
    r = client.post(
        "/api/v1/runs",
        json={
            "agent": "extractor",
            "input": "Satya Nadella runs Microsoft from Redmond.",
        },
    )
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    body = wait_for_status(client, run_id, "completed")
    assert body["artifacts"][0]["kind"] == "structured_output"
    data = body["artifacts"][0]["data"]
    assert set(data) >= {"entities", "language", "summary"}
```

- [x] **Step 6: Write the memory-runs tests**

Create `tests/test_memory_runs.py`:

```python
from __future__ import annotations

from typing import Any

from pydantic_ai.models.test import TestModel

from tests.conftest import _test_session_maker, wait_for_status


async def _read_history(conversation_id: str) -> list[Any]:
    from app.agents.memory.repository import MemoryRepository

    session = _test_session_maker()
    try:
        return await MemoryRepository(session).get(conversation_id)
    finally:
        await session.close()


def _texts(messages: list[Any]) -> list[str]:
    out = []
    for message in messages:
        for part in getattr(message, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, str):
                out.append(content)
    return out


async def test_run_persists_history(client, agent_model) -> None:
    agent_model(TestModel(custom_output_text="hello there"))
    r = client.post(
        "/api/v1/runs",
        json={"agent": "generalist", "input": "hi", "conversation_id": "c-mem-1"},
    )
    assert r.status_code == 202
    body = wait_for_status(client, r.json()["run_id"], "completed")
    assert body["conversation_id"] == "c-mem-1"
    messages = await _read_history("c-mem-1")
    assert len(messages) >= 2
    texts = _texts(messages)
    assert "hi" in texts
    assert "hello there" in texts


async def test_second_run_replays_stored_history(client, agent_model) -> None:
    agent_model(TestModel(custom_output_text="first-reply"))
    r1 = client.post(
        "/api/v1/runs",
        json={"agent": "generalist", "input": "one", "conversation_id": "c-replay"},
    )
    wait_for_status(client, r1.json()["run_id"], "completed")
    count1 = len(await _read_history("c-replay"))

    agent_model(TestModel(custom_output_text="second-reply"))
    r2 = client.post(
        "/api/v1/runs",
        json={"agent": "generalist", "input": "two", "conversation_id": "c-replay"},
    )
    wait_for_status(client, r2.json()["run_id"], "completed")
    count2 = len(await _read_history("c-replay"))
    assert count2 > count1
    texts = _texts(await _read_history("c-replay"))
    assert "one" in texts
    assert "two" in texts


async def test_explicit_message_history_persisted(client, agent_model) -> None:
    agent_model(TestModel(custom_output_text="reply"))
    r = client.post(
        "/api/v1/runs",
        json={
            "agent": "generalist",
            "input": "now",
            "conversation_id": "c-explicit",
            "message_history": [{"role": "user", "content": "explicit-turn"}],
        },
    )
    wait_for_status(client, r.json()["run_id"], "completed")
    texts = _texts(await _read_history("c-explicit"))
    assert "explicit-turn" in texts
    assert "now" in texts


def test_sync_poll_is_always_available(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": "hi"})
    run_id = r.json()["run_id"]
    # Even with no subscriber, polling reflects the full state.
    body = wait_for_status(client, run_id, "completed")
    assert body["run_id"] == run_id
```

- [x] **Step 7: Extend the error-envelope tests for the real app**

Append to `tests/test_error_envelope.py`:

```python
def test_real_app_404_envelope(client) -> None:
    r = client.get("/api/v1/runs/nope")
    body = r.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details", "run_id"}
    assert body["error"]["code"] == "run_not_found"


def test_real_app_unknown_agent_envelope(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "ghost", "input": "hi"})
    body = r.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "unknown_agent"
    assert body["error"]["run_id"] is None


def test_real_app_validation_envelope(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": ""})
    body = r.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]
```

- [x] **Step 8: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_runs.py tests/test_runs_cancel.py tests/test_runs_events.py tests/test_agents.py tests/test_extractor.py tests/test_memory_runs.py tests/test_error_envelope.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.runs'`.

- [x] **Step 9: Create `app/api/runs.py`**

Create `app/api/runs.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.api.errors import AppError
from app.runs.models import RunMessage, RunResponse
from app.runs.registry import (
    CancelConflictError,
    RunNotFoundError,
    SseBusyError,
)
from app.runs.sse import stream_events

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


class CreateRunRequest(BaseModel):
    agent: str = "generalist"
    input: str = Field(..., min_length=1)
    conversation_id: str | None = None
    message_history: list[RunMessage] | None = None
    tools: list[str] | None = None
    capabilities: list[str] | None = None
    max_steps: int = Field(default=8, ge=1, le=20)
    metadata: dict | None = None


@router.post("", status_code=202, response_model=RunResponse)
async def create_run(body: CreateRunRequest, request: Request) -> RunResponse:
    container = request.app.state.container
    definition = container.agents.definitions.get(body.agent)
    if definition is None:
        raise AppError(
            422,
            "unknown_agent",
            f"unknown agent {body.agent!r}",
            details={"available": sorted(container.agents.definitions)},
        )
    record = await container.runs.create(body, container)
    return RunResponse.from_record(record)


@router.get("", response_model=list[RunResponse])
async def list_runs(request: Request) -> list[RunResponse]:
    records = await request.app.state.container.runs.list()
    return [RunResponse.from_record(record) for record in records]


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, request: Request) -> RunResponse:
    registry = request.app.state.container.runs
    try:
        record = await registry.get(run_id)
    except RunNotFoundError:
        raise AppError(
            404, "run_not_found", f"run {run_id} does not exist", run_id=run_id
        ) from None
    return RunResponse.from_record(record)


@router.get("/{run_id}/events")
async def stream_run_events(run_id: str, request: Request) -> EventSourceResponse:
    registry = request.app.state.container.runs
    try:
        record, replay = await registry.claim_subscriber(run_id)
    except RunNotFoundError:
        raise AppError(
            404, "run_not_found", f"run {run_id} does not exist", run_id=run_id
        ) from None
    except SseBusyError:
        raise AppError(
            409,
            "sse_busy",
            f"run {run_id} already has an SSE subscriber",
            run_id=run_id,
        ) from None
    return EventSourceResponse(
        stream_events(record, registry, replay),
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/{run_id}/cancel", status_code=202, response_model=RunResponse)
async def cancel_run(run_id: str, request: Request) -> RunResponse:
    registry = request.app.state.container.runs
    try:
        record = await registry.cancel(run_id)
    except RunNotFoundError:
        raise AppError(
            404, "run_not_found", f"run {run_id} does not exist", run_id=run_id
        ) from None
    except CancelConflictError:
        raise AppError(
            409,
            "cancel_conflict",
            f"run {run_id} is already terminal",
            run_id=run_id,
        ) from None
    return RunResponse.from_record(record)
```

- [x] **Step 10: Create `app/api/agents.py`**

Create `app/api/agents.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agents.definitions import AgentDefinition
from app.api.errors import AppError

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


class AgentSpecOut(BaseModel):
    name: str
    description: str
    instructions_key: str
    output_type: Literal["string", "structured_output"]
    output_schema: dict[str, Any] | None = None
    tools: list[str]
    capabilities: list[str]
    uses_memory: bool
    default_max_steps: int

    @classmethod
    def from_definition(cls, definition: AgentDefinition) -> "AgentSpecOut":
        return cls(
            name=definition.name,
            description=definition.description,
            instructions_key=definition.instructions,
            output_type=definition.output_type,
            output_schema=definition.output_schema,
            tools=list(definition.tools),
            capabilities=list(definition.capabilities),
            uses_memory=definition.uses_memory,
            default_max_steps=definition.default_max_steps,
        )


@router.get("", response_model=list[AgentSpecOut])
async def list_agents(request: Request) -> list[AgentSpecOut]:
    registry = request.app.state.container.agents
    return [AgentSpecOut.from_definition(d) for d in registry.definitions.values()]


@router.get("/{name}", response_model=AgentSpecOut)
async def get_agent(name: str, request: Request) -> AgentSpecOut:
    registry = request.app.state.container.agents
    definition = registry.definitions.get(name)
    if definition is None:
        raise AppError(404, "agent_not_found", f"agent {name!r} does not exist")
    return AgentSpecOut.from_definition(definition)
```

- [x] **Step 11: Update `app/api/router.py`**

Replace the entire contents of `app/api/router.py` with:

```python
from __future__ import annotations

from fastapi import APIRouter

from app.api.agents import router as agents_router
from app.api.runs import router as runs_router
from app.features.chat.router import router as chat_router
from app.features.extract.router import router as extract_router
from app.features.memory.router import router as memory_router
from app.features.skills.router import router as skills_router
from app.features.tasks.router import router as tasks_router
from app.features.tools.router import router as tools_router

api_router = APIRouter()
api_router.include_router(runs_router)
api_router.include_router(agents_router)
# Legacy routers stay mounted until Task 10 deletes the features slice.
api_router.include_router(chat_router)
api_router.include_router(memory_router)
api_router.include_router(tools_router)
api_router.include_router(skills_router)
api_router.include_router(tasks_router)
api_router.include_router(extract_router)
```

- [x] **Step 12: Update `app/main.py`**

Replace the entire contents of `app/main.py` with:

```python
"""FastAPI application factory.

Lifespan builds the shared ``AppContainer`` (config, LLM model, prompt engine,
agent registry, run registry) and the DB pool; middleware is registered
centrally in ``core.middleware``; error handlers in ``api.errors``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.router import api_router
from app.core.config import settings
from app.core.container import build_container, close_container
from app.core.db import dispose_db, init_db
from app.core.middleware import register_middleware


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Build shared singletons (touching the model creates its HTTP client
    # up-front; agents close their own clients after each run).
    container = build_container()
    _app.state.container = container
    init_db()
    try:
        yield
    finally:
        # Cancel any in-flight runs; streams close without a terminal event.
        await container.runs.shutdown()
        await dispose_db()
        close_container()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agents - pydantic-ai + DeepSeek",
        version="0.1.0",
        description="Run-centric FastAPI server showcasing pydantic-ai with DeepSeek.",
        lifespan=lifespan,
    )
    register_middleware(app)
    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
```

- [x] **Step 13: Run the new tests**

Run: `uv run pytest tests/test_runs.py tests/test_runs_cancel.py tests/test_runs_events.py tests/test_agents.py tests/test_extractor.py tests/test_memory_runs.py tests/test_error_envelope.py -q`
Expected: `27 passed` (7 runs + 4 cancel + 4 events + 4 agents + 1 extractor + 4 memory + 3 envelope additions).

- [x] **Step 14: Run the whole suite**

Run: `uv run pytest -q`
Expected: `87 passed` (60 + 27 new).

- [x] **Step 15: Commit**

```bash
git add app/api/runs.py app/api/agents.py app/api/router.py app/main.py tests/test_runs.py tests/test_runs_cancel.py tests/test_runs_events.py tests/test_agents.py tests/test_extractor.py tests/test_memory_runs.py tests/test_error_envelope.py
git commit -m "feat: add runs and agents HTTP routers with error and SSE envelopes"
```

---

## Task 9: MCP server (FastMCP, stdio)

**Files:**
- Create: `app/mcp_server.py`
- Modify: `pyproject.toml` (add `[project.scripts]` entry)
- Test: `tests/test_mcp.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp.py`:

```python
from __future__ import annotations

import json

import pytest

from app.mcp_server import app as mcp_app


async def test_tools_listed() -> None:
    tools = await mcp_app.list_tools()
    names = {tool.name for tool in tools}
    assert {"calculator", "fetch", "current_time", "dispatch_skill"} <= names


async def test_call_calculator() -> None:
    _content, structured = await mcp_app.call_tool("calculator", {"expression": "1+1"})
    assert structured["result"] == "2"


async def test_call_fetch_uses_stub() -> None:
    # The autouse conftest patch keeps http_fetch off the network.
    _content, structured = await mcp_app.call_tool("fetch", {"url": "http://example.com"})
    assert structured["result"] == "stub-body"


async def test_call_current_time() -> None:
    _content, structured = await mcp_app.call_tool("current_time", {})
    assert structured["result"].endswith("Z") or "+00:00" in structured["result"]


async def test_prompts_listed() -> None:
    prompts = await mcp_app.list_prompts()
    names = {prompt.name for prompt in prompts}
    assert {"summarizer", "translator", "code_reviewer"} <= names


async def test_catalog_resource_lists_agents() -> None:
    contents = await mcp_app.read_resource("agents://catalog")
    payload = json.loads(contents[0].content)
    agent_names = {agent["name"] for agent in payload["agents"]}
    assert agent_names == {"generalist", "extractor"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.mcp_server'`.

- [ ] **Step 3: Create `app/mcp_server.py`**

Create `app/mcp_server.py`:

```python
"""Standalone FastMCP (stdio) server exposing the shared tools, skill prompts,
and an ``agents://catalog`` resource.

Run with ``uv run python -m app.mcp_server``.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from app.agents import tools as tools_module
from app.agents.registry import load_agent_registry
from app.agents.skills import dispatch_skill
from app.core.prompts import get_engine

app = FastMCP("agents")

_registry = load_agent_registry()


@app.tool(name="calculator")
def _calculator(expression: str) -> str:
    """Evaluate a safe numeric expression."""
    return tools_module.calculator(expression)


@app.tool(name="fetch")
async def _fetch(url: str, timeout: float = 10.0) -> str:
    """Fetch up to 4 KiB of text from an HTTP URL."""
    return await tools_module.http_fetch(url, timeout=timeout)


@app.tool(name="current_time")
def _current_time() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return tools_module.current_time()


@app.tool(name="dispatch_skill")
async def _dispatch_skill(skill_name: str, input_text: str) -> str:
    """Run a registered skill (summarizer/translator/code_reviewer)."""
    return await dispatch_skill(skill_name, input_text)


@app.prompt(name="summarizer")
def _summarizer(text: str) -> str:
    """Summarise text into bullet points."""
    return get_engine().render("skill_summarizer") + "\n\nUser text:\n" + text


@app.prompt(name="translator")
def _translator(text: str, target_language: str = "French") -> str:
    """Translate text into a target language."""
    return (
        get_engine().render("skill_translator")
        + f"\n\nTarget language: {target_language}\n\nUser text:\n{text}"
    )


@app.prompt(name="code_reviewer")
def _code_reviewer(code: str) -> str:
    """Review a code snippet."""
    return get_engine().render("skill_code_reviewer") + "\n\nUser code:\n" + code


@app.resource("agents://catalog")
def _catalog() -> str:
    """JSON document listing every declarative agent spec."""
    specs = [
        {
            "name": definition.name,
            "description": definition.description,
            "tools": list(definition.tools),
            "capabilities": list(definition.capabilities),
            "uses_memory": definition.uses_memory,
            "default_max_steps": definition.default_max_steps,
            "output_type": definition.output_type,
            "output_schema": definition.output_schema,
        }
        for definition in _registry.definitions.values()
    ]
    return json.dumps({"agents": specs}, indent=2)


def main() -> None:
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add the console-script entry point**

In `pyproject.toml`, after the `[tool.pytest.ini_options]` block, append:

```toml
[project.scripts]
agents-mcp = "app.mcp_server:main"
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_mcp.py -v`
Expected: `6 passed`.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: `93 passed` (87 + 6 new).

- [ ] **Step 7: Commit**

```bash
git add app/mcp_server.py pyproject.toml tests/test_mcp.py
git commit -m "feat: add FastMCP stdio server sharing the common tool callables"
```

---

## Task 10: Delete the legacy features slice

**Files:**
- Delete: `app/features/` (entire directory)
- Delete: `tests/test_chat.py`, `tests/test_tasks.py`, `tests/test_memory.py`, `tests/test_extract.py`
- Modify: `tests/conftest.py` (drop legacy imports and patches)
- Modify: `app/api/router.py` (new routers only)
- Modify: `app/core/prompts.yml` (drop the obsolete keys)

- [ ] **Step 1: Delete the legacy source tree and its tests**

Run:

```bash
rm -rf app/features
rm tests/test_chat.py tests/test_tasks.py tests/test_memory.py tests/test_extract.py
```

- [ ] **Step 2: Update `tests/conftest.py` to the final form**

Replace the entire contents of `tests/conftest.py` with:

```python
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
from collections.abc import AsyncIterator, Iterator
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
from app.agents.memory.models import Conversation, Message
from app.core.db import Base, get_session
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


def wait_for_status(client: TestClient, run_id: str, expected: str, timeout: float = 3.0) -> dict:
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
    monkeypatch.setattr(
        build_module,
        "get_model",
        lambda: _model_holder.current if _model_holder.current is not None else TestModel(),
    )
    monkeypatch.setattr(
        skills_module,
        "get_model",
        lambda: TestModel(custom_output_text="skill-output"),
    )

    # Safety net so the fetch tool never touches the network.
    monkeypatch.setattr(tools_module, "http_fetch", lambda *a, **k: "stub-body")

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
```

- [ ] **Step 3: Update `app/api/router.py` to the final form**

Replace the entire contents of `app/api/router.py` with:

```python
from __future__ import annotations

from fastapi import APIRouter

from app.api.agents import router as agents_router
from app.api.runs import router as runs_router

api_router = APIRouter()
api_router.include_router(runs_router)
api_router.include_router(agents_router)
```

- [ ] **Step 4: Drop the obsolete prompt-catalog keys**

Replace the entire contents of `app/core/prompts.yml` with:

```yaml
# Central prompt catalog.
# Maps a logical ``task`` (and optional ``variant``) to a template path and a
# version, so business code references prompts by name instead of file paths.
# Every path is validated at startup by ``PromptEngine``.

generalist:
  default:
    path: "agents/templates/generalist/system.jinja"
    version: "1.0"
extractor:
  default:
    path: "agents/templates/extractor/system.jinja"
    version: "1.0"
skill_summarizer:
  default:
    path: "agents/templates/skills/summarizer.jinja"
    version: "1.0"
skill_translator:
  default:
    path: "agents/templates/skills/translator.jinja"
    version: "1.0"
skill_code_reviewer:
  default:
    path: "agents/templates/skills/code_reviewer.jinja"
    version: "1.0"
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: `88 passed` — every remaining test uses the new modules only.

- [ ] **Step 6: Verify the legacy endpoint namespaces are really gone**

Run:

```bash
uv run python -c "from app.main import app; paths = sorted({r.path for r in app.routes}); print('\n'.join(p for p in paths if p.startswith('/api/v1')))"
```

Expected output contains exactly the new endpoints and nothing under `/api/v1/chat`, `/api/v1/memory`, `/api/v1/tools`, `/api/v1/skills`, `/api/v1/tasks`, or `/api/v1/extract`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: delete legacy features slice and obsolete tests"
```

---

## Task 11: Docs — README rewrite and final run

**Files:**
- Rewrite: `README.md`

- [ ] **Step 1: Rewrite the README**

Replace the entire contents of `README.md` with:

````markdown
# agents

FastAPI server showcasing [pydantic-ai](https://ai.pydantic.dev/) 2.x with the
[DeepSeek](https://deepseek.com) model, organised around **runs** instead of
one-endpoint-per-capability. The public surface is a run-centric, Agent
Protocol-flavoured HTTP API plus a standalone MCP server; everything else is an
internal module.

## Quick start

```bash
cp .env.example .env      # set DEEPSEEK_API_KEY and DATABASE_URL
uv sync
uv run alembic upgrade head            # create/upgrade DB schema
uv run uvicorn app.main:app --reload
```

Browse http://localhost:8000/docs.

## Endpoints

| Method | Path                        | Purpose                      | Success | Errors           |
|--------|-----------------------------|------------------------------|---------|------------------|
| POST   | /api/v1/runs                | Create a run                 | 202     | 422              |
| GET    | /api/v1/runs                | List runs (newest first)     | 200     | —                |
| GET    | /api/v1/runs/{run_id}       | Run status/steps/artifacts   | 200     | 404              |
| GET    | /api/v1/runs/{run_id}/events| SSE event stream             | 200     | 404, 409         |
| POST   | /api/v1/runs/{run_id}/cancel| Cancel a run                 | 202     | 404, 409         |
| GET    | /api/v1/agents              | List declarative agent specs | 200     | —                |
| GET    | /api/v1/agents/{name}       | Single agent spec            | 200     | 404              |

The old endpoint namespaces (`/api/v1/chat*`, `/api/v1/memory*`,
`/api/v1/tools`, `/api/v1/skills`, `/api/v1/tasks`, `/api/v1/extract`) are
**removed** and do not redirect. Use the run API instead:

- Chat / tools / skills / multi-step tasks / memory → a run of the
  **`generalist`** agent.
- Structured extraction → a run of the **`extractor`** agent.

### Create a run

```bash
curl -i -X POST http://localhost:8000/api/v1/runs \
  -H 'content-type: application/json' \
  -d '{"agent":"generalist","input":"What is (1+2)*3?","max_steps":8}'
```

Returns `202 Accepted` with a `RunResponse` in `status: "pending"`:

```json
{
  "run_id": "…",
  "agent": "generalist",
  "status": "pending",
  "conversation_id": null,
  "created_at": "…",
  "started_at": null,
  "finished_at": null,
  "steps": [],
  "artifacts": [],
  "usage": null,
  "error": null
}
```

`conversation_id` is minted by the server for memory-enabled agents and
returned once the run starts. `message_history` (`{role, content}` pairs)
replays explicit multi-turn context and takes precedence over stored history.
`tools` restricts the agent to a subset of its tools by name; `capabilities`
enables declared capabilities (e.g. `["thinking"]`); `max_steps` bounds model
requests (1-20, default 8); `metadata` is echoed in the run record.

### Poll

```bash
curl http://localhost:8000/api/v1/runs/<run_id>
```

Returns the authoritative `RunResponse` at any time — status, accumulated
`steps`, `artifacts`, `usage`, and `error` — whether or not anything is
subscribed to the event stream.

### Stream

```bash
curl -N http://localhost:8000/api/v1/runs/<run_id>/events
```

`text/event-stream` frames with an OpenAI-Responses-shaped envelope:

```
event: response.created
data: {"type":"response.created","run_id":"…","sequence":1,"created_at":"…","data":{"agent":"generalist","conversation_id":"…","input":"…"}}
```

Event types: `response.created`, `response.output_text.delta`,
`response.output_text.done`, `run.step`, `response.completed`,
`response.failed`, `run.cancelled`, `ping`. Every event carries `type`,
`run_id`, `sequence` (monotonic, starts at 1) and `created_at`. The terminal
event (`response.completed` / `response.failed` / `run.cancelled`) is always
the last frame, after which the server closes the stream.

`response.output_text.*` events are emitted **only** by string-output agents
(`generalist`). Structured-output agents (`extractor`) emit
`response.created` → (optional `run.step`) → `response.completed` with a
`structured_output` artifact.

At most **one** SSE subscriber is accepted per run; a second subscriber gets
`409 sse_busy`. After the sole subscriber disconnects, no further subscriber
is accepted — reconnect via polling.

### Cancel

```bash
curl -i -X POST http://localhost:8000/api/v1/runs/<run_id>/cancel
```

`202` with the run in `status: "cancelled"`; cancelling a terminal run yields
`409 cancel_conflict`; an unknown run yields `404`.

## Run lifecycle

```
pending ──► running ──► completed
              │  │
              │  └──► failed (exception / retry budget / RUN_TIMEOUT_SECONDS)
              └────► cancelled (cancel request from pending or running)
```

Runs live **in memory** and die with the process: there is no run persistence
and no queue. Treat `404 run_not_found` after a restart as "the run is gone".

## Errors

Every error response uses one envelope:

```json
{ "error": { "code": "…", "message": "…", "details": null, "run_id": null } }
```

Codes: `validation_error` (422), `unknown_agent` (422), `run_not_found` (404),
`agent_not_found` (404), `sse_busy` (409), `cancel_conflict` (409),
`internal_error` (500). Run-level failures are recorded in the run's `error`
field and the `response.failed` event with codes `timeout`, `model_error`, or
`tool_error`.

## MCP server

A standalone [FastMCP](https://github.com/modelcontextprotocol/python-sdk)
server (stdio) exposes the same tools and skills as the run API:

```bash
uv run python -m app.mcp_server
# or: uv run agents-mcp
```

Exposed surface:

- **Tools:** `calculator(expression)`, `fetch(url)`, `current_time()`,
  `dispatch_skill(skill_name, input_text)`.
- **Prompts:** `summarizer(text)`, `translator(text, target_language)`,
  `code_reviewer(code)`.
- **Resource:** `agents://catalog` — JSON listing every agent spec.

Example with Claude:

```bash
claude mcp add agents -- uv run python -m app.mcp_server
```

Memory is intentionally not exposed over MCP; it belongs to the run API's
`conversation_id` contract.

## Agent specs

Agents are declarative YAML files in `app/agents/specs/`. To add an agent,
drop in a spec:

```yaml
name: myagent
description: "What this agent does."
instructions: generalist       # key into app/core/prompts.yml
output_type: string            # or structured_output
tools: [calculator]            # names from the shared registry
capabilities: []
uses_memory: false
default_max_steps: 8
```

Specs are validated at startup by the `AgentDefinition` pydantic model; a bad
spec fails fast. The registry (`app/agents/registry.py`) resolves them into
pydantic-ai agents with `tools=` registration, capabilities, and output
schemas.

## Database

Conversation memory is persisted in Postgres via async SQLAlchemy (`asyncpg`)
with Alembic migrations; the schema is unchanged. Tests use an in-memory
SQLite engine (`tests/conftest.py`), so they need no running Postgres.
Migrations live in `app/core/migrations`.

## Tests

```bash
uv run pytest
```

Powered by pydantic-ai `TestModel`/`ScriptedTestModel`, in-memory SQLite, and
a stubbed `http_fetch` — no network calls.
````

- [ ] **Step 2: Final full-suite run**

Run: `uv run pytest -q`
Expected: `88 passed`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for the run-centric API and MCP server"
```



