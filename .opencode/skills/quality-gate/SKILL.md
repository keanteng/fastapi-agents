---
name: quality-gate
description: Run the full quality pipeline — rewrite/extend tests, lint, format, and type-check — before marking any change complete. Use me after every code edit.
license: MIT
compatibility: opencode
metadata:
  audience: all
  workflow: code-change
---

## What I do

I enforce a mandatory quality pipeline after every code change:

1. **Tests** — write or update unit tests that cover the change, then run them
2. **Linting** — run `ruff check` and fix issues
3. **Formatting** — run `ruff format --check` (or `--diff`) to verify formatting
4. **Type checking** — run `pyright app/ tests/` (install if missing: `uv pip install pyright`)
5. **Integration test** — run the full test suite one final time

## Exact commands (run in this order, stop on failure)

| Step | Command | Purpose |
|------|---------|---------|
| 1 | `uv run pytest tests/ -x` | Run test suite, stop at first failure |
| 2 | `ruff check app/ tests/ --fix` | Auto-fix lint issues |
| 3 | `ruff format --check app/ tests/` | Verify formatting; use `ruff format app/ tests/` to auto-fix |
| 4 | `uv pip install pyright && uv run pyright app/ tests/` | Type-check (install pyright if absent) |
| 5 | `uv run pytest tests/` | Final full test suite pass (no `-x`) |

## When to use me

- After **every** code change, before declaring work complete
- When a user asks to "clean up", "verify", or "run checks"
- Before committing or opening a PR

## Rules

- Never skip a step. If `ruff check` fixes files, re-run tests (step 1) again.
- If `ruff format` reformats files, re-run tests (step 1) and then `ruff check` (step 2) again.
- If a step fails, fix the issue **in the source code** (not by disabling the check) and re-run from step 1.
- **Type-check failures must be fixed with proper types**, never with `# type: ignore` or `# pyright: ignore` comments. Use explicit type annotations, `Protocol` subtypes, `TypedDict`, `cast()`, or narrow the logic instead. If a library lacks stubs, add a `pyrightconfig.json` or stub file — do not suppress the error at the call site.
- Tests go in `tests/` next to the relevant feature; use the existing `conftest.py` fixtures.
- Follow the existing pattern: tests use `pytest-asyncio` with `asyncio_mode = "auto"` and `TestModel` from pydantic-ai.
