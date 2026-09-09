# agents (backend)

FastAPI server showcasing [pydantic-ai](https://ai.pydantic.dev/) 2.x with the
[DeepSeek](https://deepseek.com) model, organised around **runs** instead of
one-endpoint-per-capability. The public surface is a run-centric, Agent
Protocol-flavoured HTTP API plus a standalone MCP server; everything else is an
internal module.

This is the `backend/` half of the monorepo (see the root `README.md`); the
chat UI lives in `frontend/`. Run every command below **from this directory**.

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
| GET    | /api/v1/conversations       | List conversations (newest first) | 200 | —             |
| GET    | /api/v1/conversations/{id}  | Conversation transcript as DTOs | 200 | 404          |
| DELETE | /api/v1/conversations/{id}  | Delete a conversation        | 204     | 404              |
| POST   | /api/v1/uploads             | Upload a file (returns sha1 id) | 201 | 413, 422       |
| GET    | /api/v1/uploads/{id}        | Upload metadata              | 200     | 404              |

The old endpoint namespaces (`/api/v1/chat*`, `/api/v1/memory*`,
`/api/v1/tools`, `/api/v1/skills`, `/api/v1/tasks`, `/api/v1/extract`) are
**removed** and do not redirect. Use the run API instead:

- Chat / tools / skills / multi-step tasks / memory → a run of the
  **`generalist`** agent.
- Structured extraction, document reading and compliance checks are **tools**
  (`extract_entities`, `document_text`, `check_compliance`) the generalist
  calls itself when asked — no separate agent mode is needed.

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
requests (1-20); when omitted the agent spec's `default_max_steps` is used
(`generalist`: 16); `metadata` is echoed in the run record. `usage` reports
tokens plus the model-request and tool-call counts; when a completed run used
its whole step budget (the model stopped because no requests/tool calls were
left), the run carries a `note` explaining the reply may be incomplete.

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
`response.output_text.done`, `run.tool.started`, `run.step`,
`response.completed`, `response.failed`, `run.cancelled`, `ping`. Every event
carries `type`, `run_id`, `sequence` (monotonic, starts at 1) and `created_at`.
The terminal event (`response.completed` / `response.failed` / `run.cancelled`)
is always the last frame, after which the server closes the stream.

`run.tool.started` is emitted when a tool call begins (additive live event) with
`tool_call_id`, `name`, `args`, and `started_at`, so clients can open a "tool
running" card before the tool returns; the matching `run.step` carries the same
`tool_call_id` once it finishes. `run.step` may also carry steps of type
`progress` (long-running tools stream human-readable status lines this way).

`response.output_text.*` events are emitted only by string-output agents — the
single `generalist` agent. Sub-agent results (e.g. the JSON returned by the
`extract_entities` tool) surface as `run.step` tool results, never as
`output_text` events.

At most **one** SSE subscriber is accepted per run; a second subscriber gets
`409 sse_busy`. After the sole subscriber disconnects, no further subscriber
is accepted — reconnect via polling.

### Cancel

```bash
curl -i -X POST http://localhost:8000/api/v1/runs/<run_id>/cancel
```

`202` with the run in `status: "cancelled"`; cancelling a terminal run yields
`409 cancel_conflict`; an unknown run yields `404`.

## Document uploads & compliance

Upload a file once, then let the chat agent read or compliance-check it:

```bash
curl -i -X POST http://localhost:8000/api/v1/uploads \
  -F file=@contract.pdf            # -> {"upload_id":"…","file_name":"…","size":…}
```

Uploads are stored under `UPLOAD_DIR` keyed by the sha1 of their bytes (so
re-uploading identical content returns the same id). Allowed types: `pdf`,
`docx`, `txt`, `md`, `png`, `jpg`, `jpeg`, `webp`.

The **generalist** agent exposes three document/text tools:

- `document_text(upload_id)` — textract-style text extraction
  (poppler `pdftotext`/`pdftoppm`, tesseract OCR for scans, `python-docx` for
  `.docx`). Ask the agent to read an uploaded file and it will use this.
- `check_compliance(upload_id)` — runs a PII / sensitive-data compliance check:
  text extraction → regex scanning over configurable sensitive-data rules →
  optional vision analysis of page images with `deepseek-v4-flash-vision-exp`
  → an LLM verdict (`overall_compliant`, `risk_level`, summary, findings with
  evidence/page/reason/recommendation). High-severity automated hits always
  override an LLM that would have missed them.
- `extract_entities(text)` — runs an internal structured-output sub-agent
  (`ExtractionResult`: PER/ORG/LOC/DATE/MISC entities, language, summary) and
  returns JSON. The generalist calls it when asked to extract entities from a
  message or an uploaded file (reading the file first via `document_text`).

Progress inside long-running document tools is streamed as `run.step` events of
type `progress`, so the web UI shows a live pipeline. Vision analysis is
enabled with `DOC_VISION_ENABLED` and gated behind `DOC_MAX_VISION_PAGES`;
sensitive-data rules live in `app/documents/rules.py` and can be extended via
an optional `COMPLIANCE_RULES_PATH` YAML file (`rules:` list).

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
