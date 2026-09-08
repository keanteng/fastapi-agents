# agents

Monorepo for the **agents** project — a FastAPI + pydantic-ai backend with a
run-centric API, and a small Vite/TypeScript chat UI.

## Layout

| Path        | Contents                                                            |
|-------------|---------------------------------------------------------------------|
| `backend/`  | FastAPI server, agents, memory, document/compliance pipeline, tests |
| `frontend/` | Vite + TypeScript chat app (conversation history, live tool cards)   |

## Quick start

Backend (from `backend/`):

```bash
cp .env.example .env   # set DEEPSEEK_API_KEY and DATABASE_URL
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload   # http://localhost:8000/docs
```

Frontend (from `frontend/`):

```bash
npm install
npm run dev   # http://localhost:5173 (proxies /api to :8000)
```

See `backend/README.md` for the full API and agent documentation.
