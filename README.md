# agents

FastAPI server showcasing [pydantic-ai](https://ai.pydantic.dev/) with the
[DeepSeek](https://deepseek.com) model, organised using **vertical slice
architecture**. Each feature (chat, memory, tools, skills, multi-step tasks,
structured extraction) owns its router, schemas, service, agent, tools and
Jinja templates.

## Run

```bash
cp .env.example .env      # set DEEPSEEK_API_KEY and DATABASE_URL
uv sync
uv run alembic upgrade head            # create/upgrade DB schema
uv run uvicorn app.main:app --reload
```

Browse http://localhost:8000/docs.

## Database

Conversation memory is persisted in Postgres via async SQLAlchemy
(`asyncpg`) with Alembic migrations. Set `DATABASE_URL` in `.env`; the
engine pool is sized by `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`. Tests use an
in-memory SQLite engine (see `tests/conftest.py`), so they don't need a
running Postgres.

Migrations live in `app/core/migrations`. To add one after changing ORM
models in `app/features/<slice>/models.py`:

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

> The ORM models for each slice must be imported by
> `app/core/migrations/env.py` (or another `Base.metadata` collector) so
> Alembic sees them — the memory slice is already wired up there.

## Endpoints

| Method | Path                       | Showcase                                  |
|--------|----------------------------|-------------------------------------------|
| POST   | /api/v1/chat               | simple chat                               |
| POST   | /api/v1/chat/stream        | streaming chat (SSE)                      |
| POST   | /api/v1/memory             | provision a conversation (server uuid4)  |
| GET    | /api/v1/memory/{conv_id}   | list conversation memory (stable DTOs)    |
| POST   | /api/v1/memory/{conv_id}   | append a message to memory                |
| DELETE | /api/v1/memory/{conv_id}   | clear memory                              |
| POST   | /api/v1/memory/{conv_id}/chat | chat with message_history replay       |
| POST   | /api/v1/tools              | function tool calling                     |
| POST   | /api/v1/skills             | skills orchestration via tool dispatch   |
| POST   | /api/v1/tasks              | multi-step task via delegating sub-agents |
| POST   | /api/v1/extract            | structured output (Pydantic model)        |

`GET /api/v1/memory/{conv_id}` returns `messages` as stable DTOs
(`MessageOut`/`PartOut`) decoupled from pydantic-ai's internal message
shape; raw `ModelMessage` payloads are still what's stored on disk.

## Tests

```bash
uv run pytest
```

Powered by pydantic-ai `TestModel` -- no network calls.# fastapi-agents
