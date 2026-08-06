# Agent-Run API + MCP Server — Design Spec

Date: 2026-08-05
Status: Approved for implementation planning
Scope: Redesign of the public API of the `agents` repository (FastAPI + pydantic-ai + DeepSeek showcase)

---

## 1. Problem statement and goals

### 1.1 Why the current API is hard to use

The current server exposes **one endpoint per capability** — twelve endpoints
across six vertical slices (`chat`, `memory`, `tools`, `skills`, `tasks`,
`extract`). A client that wants a conversational assistant with memory, tool
calling, and skill delegation must orchestrate calls across five different
URL namespaces and keep its own mapping of which slice does what. The
endpoints are fire-and-forget POSTs: they return a final answer or a raw SSE
text stream, but expose **no run identity, no intermediate steps, no cancel
semantics, and no consistent error body**. Streaming chat yields raw text
chunks with no event envelope, so common frontend SDKs cannot consume it.

### 1.2 What "the 2026 shape" means

The agentic-AI ecosystem in 2026 has converged on a **three-layer protocol
landscape**:

| Layer | Role | Examples |
|---|---|---|
| MCP | Agent ↔ tools: discovery and invocation of tools/resources/prompts by agents and agent-enabled clients | `mcp` SDK / FastMCP |
| Agent Protocol | Client ↔ agent: a run-centric HTTP API with polling + SSE | OpenAI Responses API, Agent Protocol (LangChain) |
| A2A | Agent ↔ agent: peer-to-peer task exchange between autonomous agents | A2A protocol (Google) |

This redesign deliberately adopts the **Agent-Protocol-shaped run API on the
HTTP side and an MCP server on the tool side**. A full **A2A server is out of
scope**: this repo has no multi-agent interop requirement (its "multi-step
tasks" are in-process sub-agent delegation, not cross-process agent
communication). Should A2A interop be needed later it can be added as a thin
adapter over the same run API; nothing in this design blocks that.

### 1.3 Goals

1. Replace the twelve endpoint-per-capability endpoints with a **run-centric
   public API** (Agent Protocol flavored): create, poll, cancel, and stream
   runs; list agents.
2. Make runs **first-class**: stable `run_id`, lifecycle state machine,
   structured steps/artifacts, and an OpenAI-Responses-style SSE event envelope
   that common frontend SDKs can consume.
3. Add a **standalone MCP server** (FastMCP, stdio) exposing the same tools and
   skills over MCP so external MCP clients (Claude, Cursor, other agents) can
   discover and call them.
4. **Modernize the pydantic-ai layer** to 2.x idioms: composable capabilities,
   declarative agent definitions (YAML agent specs), output schemas, and
   `tools=`/`toolsets=` registration — removing the pre-1.0 message-poking code
   that the current `tasks` slice relies on.
5. Keep the repo **self-contained** and keep it a **teaching showcase** for
   pydantic-ai: Python, FastAPI, pydantic-ai, FastMCP, Postgres memory.
6. Keep the **no-network test philosophy**: `TestModel`-based tests, in-memory
   SQLite, zero external calls.

---

## 2. Scope

### 2.1 In scope

- New run-centric HTTP API: `POST /api/v1/runs`, `GET /api/v1/runs`,
  `GET /api/v1/runs/{run_id}`, `GET /api/v1/runs/{run_id}/events` (SSE),
  `POST /api/v1/runs/{run_id}/cancel`.
- Agent discovery endpoints: `GET /api/v1/agents`, `GET /api/v1/agents/{name}`.
- A consistent **error envelope** applied to every error response (including
  the default FastAPI 422).
- An **SSE event envelope** (defined in §4.5) for run streaming.
- An **MCP server** (FastMCP, stdio transport) sharing the same tool/skill
  implementations as the run API.
- Modern pydantic-ai agents: declarative **YAML agent specs**, composable
  capabilities, `output_type` structured output, shared tool callables
  registered via `tools=` and `@mcp.tool`.
- Internal memory wiring: Postgres-backed conversation memory is attached to
  runs via `conversation_id`; the four public memory CRUD endpoints are
  removed.
- Reorganization of the six vertical-slice folders into internal modules.
- Test rewrite: run lifecycle, SSE envelope, agent listing, error envelope,
  MCP tool listing/calling, repository tests.
- README + endpoint documentation rewrite.
- Dependency changes: add `mcp`, bump the `pydantic-ai` floor.

### 2.2 Explicitly out of scope

- **Auth / multi-tenancy / API keys / rate limiting.** The server remains
  open and unauthenticated (as today).
- **Durable or persisted run state.** Runs live in an in-memory registry and
  die with the process. No DB schema for runs.
- **Task queues / background workers** (Celery, Arq, RQ, etc.). Execution is
  in-process asyncio tasks.
- **A2A protocol server** (§1.2).
- **Horizontal scaling** (multiple workers/instances, distributed registry,
  sticky sessions). Single process, single event loop.
- **Cancel semantics beyond in-process:** no external webhook
  cancellation, no persistence of cancel requests across restarts.
- **MCP over streamable HTTP / SSE transport.** stdio only for now (§6.4).
- **New database tables or migrations.** The existing `conversations` /
  `messages` schema is unchanged.
- **Agent-authored MCP clients** (pydantic-ai `MCP` capability that calls the
  MCP server from inside an agent run). The MCP server is an external-facing
  surface only in this iteration.

---

## 3. Architecture

### 3.1 Component diagram

```
                     ┌─────────────────────────────────────────────────┐
                     │            FastAPI app  (app.main:app)           │
                     │                                                  │
  HTTP clients ─────▶│  ┌───────────────────────────────────────────┐  │
  (SDKs, frontends)  │  │  Public HTTP layer  (app/api)              │  │
                     │  │  runs.py · agents.py · errors.py           │  │
                     │  │  sse wire via sse-starlette                 │  │
                     │  └───────────────────────┬───────────────────┘  │
                     │                          │                      │
                     │  ┌───────────────────────▼───────────────────┐  │
                     │  │  Run domain  (app/runs)                    │  │
                     │  │  registry.py  in-memory run registry       │  │
                     │  │  runner.py    asyncio task per run         │  │
                     │  │  models.py · events.py · sse.py            │  │
                     │  └───────────────────────┬───────────────────┘  │
                     │                          │                      │
                     │  ┌───────────────────────▼───────────────────┐  │
                     │  │  Agent layer  (app/agents)                 │  │
                     │  │  specs/*.yaml  declarative agent defs      │  │
                     │  │  registry.py + build.py  → pydantic-ai     │  │
                     │  │  Agent (capabilities + tools=)             │  │
                     │  └───────────────────────┬───────────────────┘  │
                     └──────────────────────────┼──────────────────────┘
                                                │ shares the same
                                                │ tool callables
                ┌───────────────────────────────┼───────────────────────────┐
                │                               │                            │
     ┌──────────▼─────────┐       ┌─────────────▼──────────┐   ┌────────────▼──────────┐
     │ Shared tools        │       │ Skills                 │   │ Memory store           │
     │ app/agents/tools.py │       │ app/agents/skills.py   │   │ app/agents/memory/      │
     │ calculator          │       │ summarizer/translator/ │   │ models.py repository.py│
     │ fetch               │       │ code_reviewer          │   │ serialize.py wiring.py │
     │ current_time        │       │ dispatch_skill         │   │ (existing Postgres     │
     └──────────┬─────────┘       └─────────────────────────┘   │  schema, unchanged)    │
                │                                               └────────────────────────┘
                │
     ┌──────────▼───────────┐
     │ MCP server            │   standalone stdio process
     │ app/mcp_server.py     │   thin adapters over the same
     │ tools · prompts ·     │   shared tool callables (single
     │ resources             │   source of truth)
     └───────────────────────┘
```

**Config and DI:** `app/core/config.py` (pydantic-settings) and
`app/core/container.py` build process-wide singletons: the LLM model
(`app/core/model.py`), the `PromptEngine` (`app/core/prompts.py`), the agent
registry, and the run registry. The MCP server builds its own container when
run standalone. The DB layer (`app/core/db.py`), middleware
(`app/core/middleware.py`), and Alembic migrations (`app/core/migrations/`)
are unchanged apart from the memory-model import path.

### 3.2 Single source of truth for tools

The same underlying Python callables back both the HTTP-run path and the MCP
path:

- `app/agents/tools.py` defines **plain, dependency-free functions**:
  `calculator(expression)`, `http_fetch(url, timeout)`, `current_time()`.
  These functions raise ordinary exceptions on failure; they know nothing
  about pydantic-ai or MCP.
- The pydantic-ai agents register them via the `Agent(..., tools=[...])`
  parameter; a thin adapter converts tool exceptions into `ModelRetry` so the
  model can self-correct (pydantic-ai idiom).
- The MCP server registers the same callables with `@mcp.tool()` decorators in
  `app/mcp_server.py`; FastMCP surfaces exceptions to the MCP client directly.

Rule: **tool logic lives only in `app/agents/tools.py` (and skill logic only
in `app/agents/skills.py`).** The agent layer and MCP layer are thin adapters
over these modules. This is what guarantees the HTTP-run API and the MCP
server cannot drift apart.

### 3.3 Agent registry and specs

`app/agents/registry.py` holds two registries:

- `AGENTS: dict[str, AgentDefinition]` — declarative agent specs loaded from
  YAML (`app/agents/specs/*.yaml`), each validated by our own pydantic model
  `AgentDefinition` (§7.2).
- `TOOLS: dict[str, Callable]` — the shared tool callables by name.

`build_agent(name: str) -> pydantic_ai.Agent` resolves a spec: binds the
model, renders instructions from the prompt catalog, attaches the requested
tools, applies output schemas, and composes capabilities. Two agents ship by
default:

| Agent | Capabilities / tools | Output | Absorbs the former slice |
|---|---|---|---|
| `generalist` | `calculator`, `fetch`, `current_time`, `dispatch_skill`, sub-agent delegation (`delegate_chat`, `delegate_tools`, `delegate_skill`), memory (`uses_memory: true`) | `str` | chat, tools, skills, tasks, memory |
| `extractor` | none (pure structured output), no memory | `ExtractionResult` | extract |

---

## 4. Public API contract

### 4.1 Endpoint summary

| Method | Path | Purpose | Success | Errors |
|---|---|---|---|---|
| `POST` | `/api/v1/runs` | Create a run | `202` | `422` |
| `GET` | `/api/v1/runs` | List runs (most recent first) | `200` | — |
| `GET` | `/api/v1/runs/{run_id}` | Run status/steps/artifacts | `200` | `404` |
| `GET` | `/api/v1/runs/{run_id}/events` | SSE event stream | `200` | `404`, `409` |
| `POST` | `/api/v1/runs/{run_id}/cancel` | Cancel a run | `202` | `404`, `409` |
| `GET` | `/api/v1/agents` | List declarative agent specs | `200` | — |
| `GET` | `/api/v1/agents/{name}` | Single agent spec | `200` | `404` |

Old endpoints (`/api/v1/chat*`, `/api/v1/memory*`, `/api/v1/tools`,
`/api/v1/skills`, `/api/v1/tasks`, `/api/v1/extract`) are **removed** and do
not 301-redirect; the README documents the replacement.

### 4.2 Run request/response models

All Pydantic models live in `app/runs/models.py` (envelope/API DTOs) and
`app/agents/definitions.py` (agent specs). Field names below are the wire
names.

**`CreateRunRequest`** (`app/api/runs.py`):

```json
{
  "agent": "generalist",
  "input": "What is (1+2)*3, then fetch https://example.com and summarise it?",
  "conversation_id": null,
  "message_history": null,
  "tools": null,
  "capabilities": null,
  "max_steps": 8,
  "metadata": null
}
```

- `agent: str = "generalist"` — name of an `AgentDefinition`; unknown names
  yield `422` with error code `unknown_agent` (§4.6).
- `input: str` (min length 1) — the user prompt for this run.
- `conversation_id: str | None` — when supplied on an agent with
  `uses_memory: true`, persisted history is replayed and the run's messages
  are persisted afterwards; otherwise the server mints one (returned in the
  response).
- `message_history: list[RunMessage] | None` — explicit multi-turn replay:
  `RunMessage` is `{role: "user" | "assistant", content: str}`. If both
  `message_history` and a `conversation_id` are given, `conversation_id`
  storage is still used to persist the run, and the explicit history takes
  precedence over stored history for replay.
- `tools: list[str] | None` — **hints** to restrict the agent to a subset of
  its registered tools by name (filtered at build time per run). `null`
  means "use all".
- `capabilities: list[str] | None` — capability hints (e.g.
  `["thinking"]`); `null` means "spec defaults". Only capability names the
  agent spec declares are honored; unknown names are ignored.
- `max_steps: int = 8, ge=1, le=20` — upper bound on model requests per run,
  mapped onto pydantic-ai `UsageLimits`.
- `metadata: dict | None` — opaque client metadata echoed in the run record.

**`RunResponse`** — returned by `POST /api/v1/runs`, `GET /api/v1/runs/{id}`,
`POST /api/v1/runs/{id}/cancel`, and used inside `GET /api/v1/runs`:

```json
{
  "run_id": "3fa85f6412345678901234567890abcdef",
  "agent": "generalist",
  "status": "pending",
  "conversation_id": null,
  "created_at": "2026-08-05T10:00:00Z",
  "started_at": null,
  "finished_at": null,
  "steps": [],
  "artifacts": [],
  "usage": {},
  "error": null
}
```

- `status` — one of `RunStatus` (§5.1).
- `steps: list[RunStep]` — `RunStep` is
  `{index: int, type: "tool_call" | "message", name: str, summary: str,
  result: str | null, started_at: datetime, finished_at: datetime | null}`.
  `tool_call` steps carry the tool name and a truncated arg summary; `message`
  steps record notable intermediate model messages (used by the extractor).
- `artifacts: list[RunArtifact]` — `RunArtifact` is
  `{name: str, kind: "text" | "structured_output" | "error", data: any}`. The
  `generalist` emits one `output` text artifact on completion; the `extractor`
  emits one `structured_output` artifact whose `data` is the validated
  `ExtractionResult` object.
- `usage` — `{input_tokens, output_tokens, requests}` once the run finishes.
- `error` — the `ErrorBody` (or `null`) when `status == "failed"`.

`POST /api/v1/runs` returns `202 Accepted` with a `RunResponse` in
`status == "pending"`. `GET /api/v1/runs` returns `list[RunResponse]` ordered
by `created_at` descending. `POST /api/v1/runs/{id}/cancel` returns `202` with
a `RunResponse` reflecting the state at cancel time (§5.3).

### 4.3 Agent discovery models

**`AgentSpecOut`** (in `app/api/agents.py`), returned by `GET /api/v1/agents`
and `GET /api/v1/agents/{name}`:

```json
{
  "name": "generalist",
  "description": "Conversational agent with tool calling, skill delegation, and memory.",
  "instructions_key": "generalist",
  "output_type": "string",
  "tools": ["calculator", "fetch", "current_time", "dispatch_skill",
            "delegate_chat", "delegate_tools", "delegate_skill"],
  "capabilities": ["thinking"],
  "uses_memory": true,
  "default_max_steps": 8
}
```

For the `extractor`, `output_type` is `"structured_output"` and the JSON
schema of the output model is included under an `output_schema` field so
clients can pre-generate validators. `GET /api/v1/agents/{name}` returns a
single `AgentSpecOut` or `404` (code `agent_not_found`).

### 4.4 Error envelope

The repo currently has no consistent error body. Every error response uses:

```json
{
  "error": {
    "code": "run_not_found",
    "message": "run 3fa85f6412345678901234567890abcdef does not exist",
    "details": null,
    "run_id": null
  }
}
```

- `code` — machine-readable string (§4.6).
- `message` — human-readable string.
- `details` — optional structured context (e.g. FastAPI 422 field errors).
- `run_id` — set when the error pertains to a run.

Implementation: a single exception handler in `app/api/errors.py` converts
`HTTPException` into the envelope; a second handler converts FastAPI's default
`RequestValidationError` into `422` with code `validation_error` and the
field errors under `details`. The default FastAPI 422 body is **not** exposed.

### 4.5 SSE event envelope

`GET /api/v1/runs/{id}/events` returns `text/event-stream` via sse-starlette
(transport only; the envelope is ours). Each frame:

```
event: <event_type>
data: <json>
```

The JSON payload follows the OpenAI Responses API envelope shape so common
frontend SDKs can consume it:

```json
{
  "type": "response.output_text.delta",
  "run_id": "3fa85f6412345678901234567890abcdef",
  "sequence": 4,
  "created_at": "2026-08-05T10:00:04Z",
  "data": {
    "delta": "The result is 9."
  }
}
```

**Event types** (all carry `type`, `run_id`, `sequence`, `created_at`):

| `type` | `data` payload | When |
|---|---|---|
| `response.created` | `{agent, conversation_id, input}` | Run registered, before execution starts |
| `response.output_text.delta` | `{delta: str}` | A text chunk from `stream_text()` |
| `response.output_text.done` | `{text: str}` | Full accumulated text, at end of output |
| `run.step` | `{step: RunStep}` | A tool call or message step completed |
| `response.completed` | `{status, usage, artifacts}` | Run reached `completed`; terminal |
| `response.failed` | `{error: ErrorBody}` | Run reached `failed`; terminal |
| `run.cancelled` | `{error: null}` | Run reached `cancelled`; terminal |
| `ping` | `{t: timestamp}` | Keepalive while running (no content change) |

**Output-type-dependent events:** `response.output_text.delta` and
`response.output_text.done` are emitted **only** by string-output agents
(`generalist`), whose execution uses `agent.run_stream(...)`. Structured-output
agents (`extractor`) execute with `agent.run(...)` and emit no
`response.output_text.*` events at all — their sequence is
`response.created` → (optional `run.step` for `message` steps) →
`response.completed` with the `structured_output` artifact. Consumers must not
assume deltas precede every completion.

**Ordering guarantees:**

1. `sequence` is a monotonically increasing integer starting at 1, unique
   within a run, assigned at emission time by the runner.
2. Events are emitted in causal order from the run's asyncio task; deltas
   precede `response.output_text.done`; `response.created` is always first.
3. A **terminal event** (`response.completed` / `response.failed` /
   `run.cancelled`) is always the last frame; the server closes the stream
   immediately after it. No events are emitted after a terminal event.
4. `ping` frames are emitted at most every 15 seconds and only while the run
   is non-terminal.
5. If a client disconnects mid-stream the server stops sending; the run keeps
   running and its state remains available via `GET /api/v1/runs/{id}`.
   At most **one** SSE subscriber is allowed per run at a time; a second
   subscriber receives `409` with code `sse_busy`. Once the sole subscriber
   disconnects, no further subscriber is accepted for that run — clients that
   reconnect read state via polling (`GET /api/v1/runs/{id}`), which always
   reflects the full truth (§9.9).

**Example stream** (a run of `generalist` that uses the calculator tool):

```
event: response.created
data: {"type":"response.created","run_id":"abc123","sequence":1,
       "created_at":"2026-08-05T10:00:00Z",
       "data":{"agent":"generalist","conversation_id":"conv-9",
               "input":"What is (1+2)*3?"}}

event: response.output_text.delta
data: {"type":"response.output_text.delta","run_id":"abc123","sequence":2,
       "created_at":"2026-08-05T10:00:02Z","data":{"delta":"The "}}

event: run.step
data: {"type":"run.step","run_id":"abc123","sequence":3,
       "created_at":"2026-08-05T10:00:03Z",
       "data":{"step":{"index":1,"type":"tool_call","name":"calculator",
                       "summary":"(1+2)*3","result":"9"}}}

event: response.output_text.delta
data: {"type":"response.output_text.delta","run_id":"abc123","sequence":4,
       "created_at":"2026-08-05T10:00:04Z","data":{"delta":"result is 9."}}

event: response.output_text.done
data: {"type":"response.output_text.done","run_id":"abc123","sequence":5,
       "created_at":"2026-08-05T10:00:04Z","data":{"text":"The result is 9."}}

event: response.completed
data: {"type":"response.completed","run_id":"abc123","sequence":6,
       "created_at":"2026-08-05T10:00:04Z",
       "data":{"status":"completed",
               "usage":{"input_tokens":120,"output_tokens":45,"requests":3},
               "artifacts":[{"name":"output","kind":"text","data":"The result is 9."}]}}
```

### 4.6 Error codes

| `code` | HTTP | Meaning |
|---|---|---|
| `validation_error` | 422 | Request body failed Pydantic validation |
| `unknown_agent` | 422 | `agent` field names an undeclared `AgentDefinition` |
| `run_not_found` | 404 | Unknown `run_id` |
| `agent_not_found` | 404 | Unknown agent name on `GET /api/v1/agents/{name}` |
| `sse_busy` | 409 | A second SSE subscriber attached to a run |
| `cancel_conflict` | 409 | Cancel requested on an already-terminal run |
| `timeout` | n/a (run error) | Run exceeded `RUN_TIMEOUT_SECONDS`; recorded in `RunResponse.error` and the `response.failed` SSE event |
| `model_error` | n/a (run error) | LLM/provider failure or retry budget exhausted; recorded in `RunResponse.error` and the `response.failed` SSE event |
| `tool_error` | n/a (run error) | Tool raised after retries exhausted; recorded in `RunResponse.error` and the `response.failed` SSE event |
| `internal_error` | 500 | Unhandled exception in the HTTP layer |

The last three codes are *run-level* errors: they never appear in an HTTP
error response, only in the run's `error` field and the `response.failed`
SSE event.

---

## 5. Run lifecycle state machine

### 5.1 States and transitions

```
        ┌──────────────┐
        │   pending    │  (run created, task not yet running)
        └──────┬───────┘
               │ task starts
               ▼
        ┌──────────────┐   normal completion   ┌───────────────┐
        │   running    │──────────────────────▶│   completed   │ (terminal)
        └──────┬───────┘                       └───────────────┘
               │ exception / retry-budget exhausted / timeout
               ▼
        ┌──────────────┐   ───────────────────▶ ┌───────────────┐
        │   failed     │                        │   cancelled   │ (terminal)
        └──────────────┘   cancel request from  └───────────────┘
        (terminal)         pending or running
```

- `pending → running`: when the run's asyncio task begins executing.
- `running → completed`: the agent run returns normally.
- `running → failed`: unhandled exception, model/tool retry budget
  exhausted, or `RUN_TIMEOUT_SECONDS` exceeded.
- `pending|running → cancelled`: a `POST /api/v1/runs/{run_id}/cancel`
  request arrives.
- `cancelled` on a `pending` run (task not yet scheduled) is handled by the
  registry marking it cancelled; the task is never started.
- No transition out of a terminal state. Cancel on a terminal run → `409
  cancel_conflict`.

### 5.2 Timeout behavior

`RUN_TIMEOUT_SECONDS` (new setting, default `300`) bounds wall-clock time of a
run from `started_at`. The runner enforces it with `asyncio.wait_for` on the
agent execution; on timeout it cancels the task and transitions the run to
`failed` with code `timeout`.

### 5.3 Cancel semantics

`POST /api/v1/runs/{id}/cancel` performs, in order:

1. Registry lock acquired; if the run is terminal → `409 cancel_conflict`.
2. State set to `cancelled`, `finished_at` recorded.
3. `task.cancel()` is called on the run's asyncio task. The in-flight agent
   run is aborted (the pending model request or tool call is interrupted).
4. The runner's `finally` block catches `asyncio.CancelledError`, emits the
   `run.cancelled` terminal event (unless a terminal event was already
   emitted by the racing completion path — see §9.6), and removes the task
   handle from the registry record.

Cancellation and natural completion can race; whichever terminal transition
acquires the registry lock first wins, and the other path is a no-op.

### 5.4 Concurrency notes

- The registry is a process-global `dict[str, RunRecord]` in
  `app/runs/registry.py`. `RunRecord` holds: `run_id`, `agent`, `status`,
  timestamps, `steps`, `artifacts`, `usage`, `error`, the `asyncio.Task`, an
  **event log** (a bounded `deque(maxlen=10_000)` of emitted events, see
  §9.9), and a wake-up `asyncio.Event`/queue that the SSE subscriber waits on
  for new events.
- All mutations go through a single `asyncio.Lock` on the registry. The
  server is single-process / single-event-loop, so runs interleave
  cooperatively; the lock additionally protects against cross-event-loop
  access from FastAPI's `TestClient` portal thread during tests.
- Runs die with the process: the registry is never written to disk or the
  database. On shutdown, running tasks are cancelled and awaiting clients see
  the stream close without a terminal event (documented; the `GET
  /api/v1/runs/{id}` endpoint 404s after restart).

---

## 6. MCP server design

### 6.1 What is exposed

A single `FastMCP("agents")` instance in `app/mcp_server.py` exposes:

- **Tools** (thin adapters over the shared callables from
  `app/agents/tools.py` and `app/agents/skills.py`):
  - `calculator(expression)` — evaluate a safe numeric expression.
  - `fetch(url)` — fetch up to 4 KiB of text from an HTTP URL.
  - `current_time()` — current UTC ISO-8601 time.
  - `dispatch_skill(skill_name, input_text)` — run a registered skill agent
    (sub-agent call, same as the generalist's tool).
- **Prompts** (rendered from the same Jinja templates as the skill agents):
  - `summarizer(text)` — summarise text into bullet points.
  - `translator(text, target_language="French")` — translate text.
  - `code_reviewer(code)` — review a code snippet.
- **Resource:** `agents://catalog` — JSON document listing every
  `AgentDefinition` (name, description, tools, capabilities, output schema)
  so MCP clients can discover what the HTTP run API offers and route work to
  it. `mcp://prompts` etc. are not added; the catalog resource is the single
  discovery surface.

Memory is intentionally **not** exposed over MCP (conversation memory belongs
to the run API's `conversation_id` contract; exposing it over MCP would leak
the internal repository layer as a public surface).

### 6.2 How it shares implementations

`app/mcp_server.py` imports the same functions as `app/agents/build.py`
imports and registers them with `@mcp.tool()`. There is exactly one copy of
each tool body (rule from §3.2). The MCP server builds its own
`AppContainer` (config + prompts) when started standalone; it does not touch
the run registry or the HTTP app.

### 6.3 How it is started

```bash
uv run python -m app.mcp_server
```

`app/mcp_server.py` exposes `app: FastMCP` (importable for tests) and a
`main()` that calls `app.run(transport="stdio")` (synchronous, blocking,
per FastMCP's API). An optional console-script entry point
`agents-mcp = "app.mcp_server:main"` may be added to `pyproject.toml` for
convenience.

### 6.4 Transport

**stdio** is the default and only supported transport in this iteration — the
standard for local MCP clients and the easiest to test in-process. The mcp SDK
supports `streamable-http` (`app.run(transport="streamable-http")`); wiring it
to uvicorn (so the FastAPI app and MCP share a port) is noted as possible
future work and is **out of scope**.

---

## 7. pydantic-ai modernization notes

### 7.1 Mapping old slices onto 2.x idioms

| Old slice | Old code | New 2.x idiom |
|---|---|---|
| chat | `chat_agent`, per-call `run()` | Folded into the `generalist` agent; plain `Agent(..., output_type=str)` with rendered instructions |
| tools | `register_tools(agent)` with `@agent.tool`/`@agent.tool_plain` | Shared callables in `app/agents/tools.py` registered via `Agent(..., tools=[...])`; tool exceptions → `ModelRetry` in a thin adapter |
| skills | `skills_agent` + `dispatch_skill` tool + `Skill` registry | `app/agents/skills.py` keeps the registry + `dispatch_skill`; skill factories build sub-agents with the shared model |
| tasks | `tasks_agent` + `_extract_steps` poking `ToolCallPart`/`ToolReturnPart` | The multi-step loop **is the run itself**; step extraction is replaced by `run.step` events emitted from pydantic-ai `hook` callbacks (e.g. `on_tool_call`), not by post-hoc message surgery; sub-agent delegation tools move to `app/agents/delegation.py` |
| memory | 4 CRUD endpoints + `chat_with_memory` | Internal `app/agents/memory/wiring.py`: load history → `message_history=`, persist `result.all_messages()` after the run, keyed by `conversation_id`; public surface is the run API only |
| extract | `extract_agent` with `output_type=ExtractionResult` | The `extractor` agent spec declares `output_schema` referencing the shared `ExtractionResult` model; the validated object is returned as a `structured_output` artifact |

The pre-1.0 message-manipulation code (`ModelRequest`/`ModelResponse`/`part_kind`
hand-walking in `tasks/service.py`) is **deleted**, not ported. Step/artifact
recording is driven by pydantic-ai's `hook` callbacks (`on_tool_call`, etc.)
at the agent boundary, which is the 2.x-supported way to observe a run.

### 7.2 Agent specs: YAML over pydantic models

Agent definitions are **YAML files** validated by our own pydantic model
`AgentDefinition` (in `app/agents/definitions.py`), not constructed as Python
objects or stored as JSON. Rationale:

1. The repo already uses YAML for its prompt catalog (`app/core/prompts.yml`);
   YAML is the established declarative format here.
2. pydantic-ai 2.9 ships YAML-based agent-spec loading and spec-schema
   generation; aligning with that ecosystem norm keeps the showcase current.
3. For a teaching showcase, a human-readable spec file with the model,
   instructions key, tools, capabilities, and memory flag is the clearest way
   to demonstrate "declarative agent definitions".

`AgentDefinition` fields (wire + file):

```yaml
# app/agents/specs/generalist.yaml
name: generalist
description: "Conversational agent with tool calling, skill delegation, and memory."
instructions: generalist            # key into app/core/prompts.yml
model: null                          # null → settings.deepseek_model
output_type: string                  # "string" | "structured_output"
output_schema: null                  # JSON schema dict when structured_output
capabilities: [thinking]            # pydantic-ai capability names the spec may
                                     #  enable; resolved against the 2.9 capability set
tools: [calculator, fetch, current_time, dispatch_skill,
        delegate_chat, delegate_tools, delegate_skill]
uses_memory: true
default_max_steps: 8
```

Spec files are loaded once at container build; a bad spec fails fast at
startup with a clear error. The registry enriches spec fields that pydantic-ai
cannot serialize (tool callables, memory wiring) at `build_agent()` time.

---

## 8. Data flow

### 8.1 Run creation → execution → streaming → completion

1. Client `POST /api/v1/runs` with `CreateRunRequest`.
2. `api/runs.py` validates the body (Pydantic). If `agent` is unknown →
   `422 unknown_agent`; else it asks `runs/registry.py` to `create()` the run:
   - run_id minted (`uuid4().hex`), `RunRecord(status="pending")` inserted
     under the registry lock.
   - `api/runs.py` responds `202` with `RunResponse(status="pending")`.
   - A background asyncio task is scheduled (not awaited by the request) that
     runs `runs/runner.py::execute_run`.
3. `execute_run` (the run task):
   a. Emits `response.created` into the run's event queue; flips
      `pending → running`.
   b. Resolves the agent via `agents/registry.py::build_agent(name, tools,
      capabilities)`.
   c. If `uses_memory` and `conversation_id`: load persisted history through
      `memory/repository.py`, replay as `message_history`; mint a
      `conversation_id` if absent.
   d. Runs the agent, branching on `output_type`:
      - `string` agents (`generalist`): `async with agent:
        async with agent.run_stream(input, message_history=…) as r:` — each
        text delta → `response.output_text.delta` event; after the stream
        ends → `response.output_text.done` event.
      - `structured_output` agents (`extractor`): `async with agent:
        result = await agent.run(input, message_history=…)` — no
        `output_text` events.
      In both branches, each tool call / delegated sub-agent → `run.step`
      event via a pydantic-ai `hook` (e.g. `on_tool_call`), also appended to
      `record.steps`.
   e. Persists messages back to memory (if `uses_memory`).
   f. Builds artifacts (text output / structured output); emits
      `response.completed`; transitions to `completed`.
4. The SSE generator (`runs/sse.py`) drains the run's event queue and writes
   sse-starlette frames; the HTTP layer flushes each frame to the client. The
   stream ends when the terminal event is drained.
5. Polling clients `GET /api/v1/runs/{id}` at any time receive the
   authoritative `RunResponse` with current status, accumulated steps,
   artifacts, and usage — independent of whether any client is subscribed to
   the SSE stream.

### 8.2 What happens on cancel

Per §5.3: the registry transitions the run to `cancelled`, cancels the
asyncio task, the runner's `finally` emits the `run.cancelled` terminal event,
and any in-flight SSE subscriber receives that event before the stream closes.
A partial in-memory history write during cancellation is acceptable (the
message row set is atomic per transaction; either the whole turn persisted or
none did).

---

## 9. Error handling and edge cases

1. **Model/provider failures.** pydantic-ai raises; `execute_run` catches,
   records `error={code: "model_error", message: <str>, details: null,
   run_id: <run_id>}`, emits `response.failed`, and transitions to `failed`.
2. **Tool errors.** Tool callables raise plain exceptions; the pydantic-ai
   adapter converts them to `ModelRetry` so the model can retry. When the
   retry budget is exhausted the run fails with `tool_error`.
3. **Validation errors.** Any `RequestValidationError` → `422
   validation_error` envelope with field errors in `details` (overrides the
   default FastAPI body).
4. **Unknown run_id** on `GET`/`cancel`/`events` → `404 run_not_found`.
5. **Unknown agent** on run creation → `422 unknown_agent`. Unknown agent on
   `GET /api/v1/agents/{name}` → `404 agent_not_found`.
6. **Cancel races.** Cancel vs. natural completion: first terminal transition
   under the registry lock wins; the loser is a no-op. Cancel on a terminal
   run → `409 cancel_conflict`. Cancel on `pending` (task unscheduled) →
   marked `cancelled`, task never started, `run.cancelled` emitted.
7. **Empty streams.** Every healthy run ends with a terminal event, so
   clients never wait forever. A string-output run that produces no text
   still emits `response.created` → `response.output_text.done` (text `""`)
   → `response.completed`. A structured-output run always emits
   `response.created` → `response.completed` (with its artifact). There is no
   path where a run finishes without emitting its terminal event.
8. **SSE disconnects.** The subscriber's queue stops being drained; the run
   continues and remains pollable. No cleanup of the run is triggered by a
   disconnect — the registry is the source of truth.
9. **SSE backpressure.** The event queue is bounded (deque, maxlen 10_000);
   in the pathological case where the runner outpaces the single subscriber,
   the oldest buffered `response.output_text.delta` events may be coalesced
   into a single delta so the terminal state is never lost. `run.step` and
   terminal events are never dropped; polling `GET /runs/{id}` always reflects
   the full truth.
10. **Process shutdown with active runs.** Running tasks are cancelled in the
    app lifespan's `finally`; in-flight SSE streams close without a terminal
    event. Documented in the README.

---

## 10. Testing strategy

Keep the existing no-network philosophy: `TestModel`/`ScriptedTestModel`,
in-memory SQLite, `http_fetch` stubbed, app lifespan hooks stubbed — all as in
`tests/conftest.py` today, with imports updated for the new module layout.
The `ScriptedTestModel` helper and the model-patching fixture carry over.

| Test file | Covers |
|---|---|
| `tests/test_runs.py` | `POST /api/v1/runs` → 202 + `status == "pending"`; `GET /runs/{id}` transitions pending→running→completed under `TestModel`; run listing order; unknown `run_id` → 404 envelope; unknown agent → 422 `unknown_agent`; validation error envelope; `max_steps` bounds rejected |
| `tests/test_runs_cancel.py` | Cancel a `pending` run → `cancelled`, no task started; cancel a running run → `cancelled` and `run.cancelled` event; cancel a completed/failed run → `409 cancel_conflict` |
| `tests/test_runs_events.py` | SSE stream via `client.stream(...)`: event order, monotonic `sequence`, terminal event last, frame format (`event:`/`data:`), `response.created` first, delta→done→completed for the generalist, `structured_output` artifact for the extractor |
| `tests/test_agents.py` | `GET /api/v1/agents` lists `generalist` + `extractor`; `GET /agents/generalist` returns spec fields; `GET /agents/nope` → 404 |
| `tests/test_error_envelope.py` | Every 4xx response body matches `{error: {code, message, details, run_id}}` |
| `tests/test_extractor.py` | Run with `agent="extractor"` under `TestModel` returns a `structured_output` artifact matching `ExtractionResult` |
| `tests/test_tools.py` (rewritten) | Shared tool callables unit-tested directly (`calculator`, `safe_eval` rejects invalid AST, `current_time`); `ScriptedTestModel` drives tool calls through the runs API and asserts `run.step` records |
| `tests/test_memory_repository.py` | Unchanged (module path updated): JSON round-trip, capacity caps, list_ids |
| `tests/test_memory_runs.py` | Run with `conversation_id` persists history (in-memory SQLite); a second run on the same id replays stored messages; explicit `message_history` takes precedence |
| `tests/test_skills.py` (rewritten) | `dispatch_skill` via the generalist under `ScriptedTestModel`; skill prompt templates render |
| `tests/test_mcp.py` | Builds the FastMCP app in-process and asserts: `list_tools()` contains `calculator`/`fetch`/`current_time`/`dispatch_skill`; `call_tool("calculator", …)` returns the expected result; `fetch` returns the stubbed body (no network); `list_prompts()` contains `summarizer`/`translator`/`code_reviewer`; the `agents://catalog` resource is readable and lists the two agents |

Old tests deleted: `test_chat.py`, `test_tasks.py`, `test_memory.py` (public
memory CRUD no longer exists), and the old `test_extract.py` (superseded by
`test_extractor.py`). `test_tools.py` and `test_skills.py` are kept but
rewritten for the new shape.

---

## 11. Migration and impact on existing files

### 11.1 New files

```
app/agents/__init__.py
app/agents/definitions.py        # AgentDefinition pydantic model (YAML schema)
app/agents/registry.py           # loads specs/, holds AGENTS + TOOLS, build_agent()
app/agents/build.py              # spec → pydantic-ai Agent wiring (tools=, capabilities, output)
app/agents/tools.py              # shared tool callables (calculator/http_fetch/current_time)
app/agents/skills.py             # skill registry + dispatch_skill + skill factories
app/agents/delegation.py         # sub-agent delegate tools (delegate_chat/delegate_tools/delegate_skill)
app/agents/specs/generalist.yaml
app/agents/specs/extractor.yaml
app/agents/models/extraction.py  # ExtractionResult + Entity (moved from features/extract/schemas.py)
app/agents/memory/__init__.py
app/agents/memory/models.py      # moved from features/memory/models.py
app/agents/memory/repository.py  # moved from features/memory/repository.py
app/agents/memory/serialize.py   # moved from features/memory/serialize.py
app/agents/memory/wiring.py      # load/persist history helpers (from memory/service.py core)
app/agents/templates/generalist/system.jinja     # from features/chat/templates/system.jinja
app/agents/templates/extractor/system.jinja      # from features/extract/templates/system.jinja
app/agents/templates/skills/summarizer.jinja     # from features/skills/templates/summarizer.jinja
app/agents/templates/skills/translator.jinja     # from features/skills/templates/translator.jinja
app/agents/templates/skills/code_reviewer.jinja  # from features/skills/templates/code_reviewer.jinja

app/runs/__init__.py
app/runs/models.py               # RunStatus, RunRecord, RunResponse, RunStep, RunArtifact, RunMessage, ErrorBody
app/runs/registry.py             # in-memory RunRegistry (dict + asyncio.Lock)
app/runs/runner.py               # execute_run asyncio task body, timeout, cancel handling
app/runs/events.py               # SSE envelope models + event builders + sequence assignment
app/runs/sse.py                  # SSE generator draining the run event queue (sse-starlette)

app/api/runs.py                  # runs router (create/list/get/cancel/events)
app/api/agents.py                # agents router (list/get)
app/api/errors.py                # error envelope + exception handlers (incl. 422 override)

# new test files
tests/test_runs.py               # run lifecycle, listing, 404/422 envelopes
tests/test_runs_cancel.py        # cancel races and conflict cases
tests/test_runs_events.py        # SSE ordering, envelope, terminal-event guarantee
tests/test_agents.py             # agent discovery endpoints
tests/test_error_envelope.py     # envelope shape on every 4xx
tests/test_extractor.py          # structured_output artifact
tests/test_memory_runs.py        # memory wiring through runs (history replay + persist)
tests/test_mcp.py                # MCP tools/prompts/resources in-process
```

The former `memory/system.jinja`, `tools/system.jinja`, `skills/orchestrator.jinja`,
and `tasks/orchestrator.jinja` templates are **obsolete**: their instruction
content is folded into the `generalist` template (memory is replayed as
`message_history`, not via a separate memory prompt). They are deleted with
`app/features/`.

### 11.2 Deleted files

```
app/features/                     # entire directory (six slices reorganized)
  chat/{agent,router,schemas,service}.py  features/chat/templates/
  memory/{agent,router,schemas,service}.py
  tools/{agent,router,schemas,service}.py
  skills/{agent,router,schemas,service,registry}.py  skills/skills/  skills/templates/
  tasks/{router,schemas,service,orchestrator,executor}.py  tasks/templates/
  extract/{agent,router,schemas,service}.py  extract/templates/
tests/test_chat.py
tests/test_tasks.py
tests/test_memory.py              # public memory CRUD endpoints no longer exist
tests/test_extract.py             # superseded by tests/test_extractor.py
```

`tests/test_tools.py`, `tests/test_skills.py`, and
`tests/test_memory_repository.py` are **kept and rewritten** (import paths and
assertions updated for the new shape) rather than deleted — see §10.

### 11.3 Renamed/moved files

| From | To |
|---|---|
| `app/features/memory/models.py` | `app/agents/memory/models.py` |
| `app/features/memory/repository.py` | `app/agents/memory/repository.py` |
| `app/features/memory/serialize.py` | `app/agents/memory/serialize.py` |
| `app/features/tools/tools.py` | `app/agents/tools.py` |
| `app/features/skills/registry.py` + `skills/skills/skills.py` + `skills/agent.py` | `app/agents/skills.py` |
| `app/features/tasks/executor.py` | `app/agents/delegation.py` |
| `app/features/tasks/orchestrator.py` (agent + limits) | `app/agents/build.py` + `default_max_steps` in spec |
| `app/features/extract/schemas.py` | `app/agents/models/extraction.py` |
| `features/chat/templates/system.jinja`, `features/extract/templates/system.jinja` | `app/agents/templates/generalist/system.jinja`, `app/agents/templates/extractor/system.jinja` |
| `features/skills/templates/{summarizer,translator,code_reviewer}.jinja` | `app/agents/templates/skills/{summarizer,translator,code_reviewer}.jinja` |

### 11.4 Modified files

- `app/main.py` — lifespan wires agent registry + run registry into the
  container; mounts the new routers; shutdown cancels running tasks.
- `app/api/router.py` — includes `runs` and `agents` routers only.
- `app/core/config.py` — adds `RUN_TIMEOUT_SECONDS` (default `300`);
  existing settings unchanged.
- `app/core/container.py` — `AppContainer` gains `agents: AgentRegistry` and
  `runs: RunRegistry`.
- `app/core/prompts.yml` — catalog keys updated: `chat` → `generalist`,
  `extract` → `extractor` (paths point at `app/agents/templates/**`); the
  obsolete `memory`, `tools`, `skills_orchestrator`, and `tasks_orchestrator`
  keys are removed (their content folds into `generalist`); the three
  `skill_*` keys are unchanged.
- `app/core/migrations/env.py` — memory model import path becomes
  `app.agents.memory.models`; no schema change.
- `pyproject.toml` — dependencies (§12); optional `agents-mcp` script.
- `uv.lock` — regenerated via `uv lock`/`uv sync` (never hand-edited).
- `tests/conftest.py` — imports/patches updated for the new layout; patches
  `build_agent`/registry so `TestModel` is injected on every agent including
  dynamically built skill agents.
- `README.md` — rewrite (below).

### 11.5 README rewrite notes

- New endpoint table (§4.1) with request/response examples and the SSE event
  types table (§4.5).
- Run lifecycle diagram (§5.1) and the "runs are in-memory, they die with the
  process" callout.
- MCP section: how to run (`uv run python -m app.mcp_server`), what it
  exposes, and an example `claude mcp add` / curl-style usage line.
- Agent spec section: how to add an agent (`app/agents/specs/*.yaml`).
- Migration note for users of the old endpoints.

---

## 12. Dependencies

`pyproject.toml` changes:

```toml
dependencies = [
    # unchanged: fastapi, uvicorn, pydantic, pydantic-settings, jinja2,
    # httpx, sqlalchemy[asyncio], asyncpg, alembic, psycopg2-binary
    "pydantic-ai[openai]>=2.9.0",   # floor raised from >=0.6
    "mcp>=1.28",                    # mcp SDK incl. mcp.server.fastmcp.FastMCP (new)
    "sse-starlette>=2.1",           # kept — SSE transport for /runs/{id}/events
    "pyyaml>=6.0",                  # kept — agent specs + prompt catalog
]

[project.scripts]
agents-mcp = "app.mcp_server:main"  # optional convenience entry point
```

- **`pydantic-ai` floor: `>=2.9.0`.** The pre-1.0 `>=0.6` floor is raised to
  the version actually in use (already locked at 2.9.0 in `uv.lock`); the new
  code targets 2.x idioms only. The `[openai]` extra stays (DeepSeek via
  `OpenAIChatModel` + `DeepSeekProvider`). The pydantic-ai `[spec]` extra is
  **not** added because the showcase uses its own `AgentDefinition` model and
  already depends on `pyyaml`.
- **`mcp>=1.28`** is added as an explicit, pinned dependency (currently
  installed transitively). It provides FastMCP.
- **`sse-starlette` stays** — it is the SSE wire transport; the event envelope
  is ours (§4.5). Hand-rolling SSE with `StreamingResponse` would work but
  would duplicate ping/disconnect handling sse-starlette already provides.
- No other dependency changes; the tool stack (fastapi, uvicorn,
  pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, psycopg2,
  httpx, jinja2) is unchanged. Dev group unchanged (pytest, pytest-asyncio,
  anyio, aiosqlite).

---

## 13. Risks and mitigations

1. **In-memory runs lose state on restart / crash.** Mitigation: this is an
   explicit design decision (no run persistence), and the README and API docs
   state it clearly; poll clients must treat `404 run_not_found` as
   "the run is gone". The polling contract (§4.2) already handles it.
2. **SSE client/SDK incompatibility from a custom envelope.** Mitigation: the
   envelope mirrors the OpenAI Responses API event names and `data` shape
   (`response.created`, `response.output_text.delta`, …), which is the
   de-facto wire standard SDKs consume; the spec pins the exact event list and
   ordering guarantees so adapters are mechanical.
3. **Tool drift between the HTTP-run path and the MCP server.** Mitigation:
   the single-source-of-truth rule (§3.2) puts all tool logic in
   `app/agents/tools.py` / `app/agents/skills.py`; the agent layer and MCP
   layer are thin adapters, and `tests/test_mcp.py` plus the runs tests both
   exercise the same callables.
4. **Cancellation leaving the pydantic-ai agent or DB session in a torn
   state.** Mitigation: cancel is confined to the run's asyncio task; the
   runner's `finally` handles `CancelledError`, and memory writes are
   transactional per turn (either the whole turn persisted or none). The
   process-wide agent/DB singletons are unaffected because each run opens its
   own short-lived session.
5. **Scope creep toward auth/durability/queues.** Mitigation: §2.2 explicitly
   fences these out; the implementation plan must not add them.

---

## 14. Decision summary

- Adopt a **run-centric Agent-Protocol-style API + a standalone MCP server**;
  A2A is explicitly out of scope.
- Public surface shrinks from 12 endpoints to **7** (§4.1); all six old slice
  endpoint namespaces are removed without redirects.
- Runs are **in-process asyncio tasks** in an in-memory registry; no queue, no
  run persistence; runs die with the process.
- Lifecycle: `pending → running → completed|failed|cancelled`, with `timeout`
  → `failed`; cancel races resolved under a registry `asyncio.Lock`.
- Consistent **error envelope** `{error: {code, message, details, run_id}}`
  everywhere, including an override of FastAPI's default 422.
- SSE **event envelope** mirrors the OpenAI Responses API: `response.created`,
  `response.output_text.delta`, `response.output_text.done`, `run.step`,
  `response.completed`, `response.failed`, `run.cancelled`, `ping`; monotonic
  `sequence`; terminal event always last; single SSE subscriber per run
  (`409 sse_busy` for a second).
- **MCP server** (FastMCP, stdio) exposes `calculator`/`fetch`/
  `current_time`/`dispatch_skill` tools, `summarizer`/`translator`/
  `code_reviewer` prompts, and the `agents://catalog` resource; started with
  `uv run python -m app.mcp_server`. streamable HTTP is future work.
- **Tools are shared** between the run API and MCP server from single callable
  modules; the two surfaces are thin adapters.
- Two **agents** ship by default: `generalist` (tools + skills + delegation +
  memory) and `extractor` (structured output). Specs are **YAML** files
  validated by an `AgentDefinition` pydantic model, loaded at startup.
- **Memory**: the Postgres-backed store is internal; attached to runs via
  `conversation_id`; the four public CRUD endpoints are removed.
- **pydantic-ai modernization**: composable capabilities, `tools=`/`toolsets=`
  registration, `output_type` structured output, run observation via hooks;
  pre-1.0 message-poking code in `tasks` is deleted.
- **Dependencies**: add `mcp>=1.28`; raise `pydantic-ai[openai]` floor to
  `>=2.9.0`; keep `sse-starlette` and `pyyaml`.
- **File layout**: `app/features/` is deleted; new internal modules
  `app/agents/`, `app/runs/`, `app/api/{runs,agents,errors}.py`,
  `app/mcp_server.py`; memory ORM/repo/serialization code is moved verbatim
  to `app/agents/memory/`.
- **Tests**: keep the `TestModel` + in-memory SQLite + no-network approach;
  new tests cover run lifecycle, cancel races, SSE ordering/envelope, error
  envelope, agent listing, extractor artifact, and in-process MCP
  tool/prompt/resource listing and calling.
