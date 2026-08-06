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
    await registry.emit(
        record, "response.created", created_data("generalist", None, "hi")
    )
    await registry.emit(record, "response.output_text.done", done_data("hi"))
    return record


async def test_emit_assigns_monotonic_sequences() -> None:
    registry = RunRegistry()
    record = RunRecord(run_id="seq", agent="generalist")
    registry.register(record)
    event1 = await registry.emit(
        record, "response.created", created_data("generalist", None, "hi")
    )
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
    await registry.emit(
        record, "response.created", created_data("generalist", None, "hi")
    )
    events = await task
    assert [e.type for e in events] == ["response.created"]


async def test_claim_subscriber_replays_buffered_events() -> None:
    registry = RunRegistry()
    record = await _finished_record(registry, "r")
    claimed, replay = await registry.claim_subscriber("r")
    assert claimed is record
    assert [e.type for e in replay] == ["response.created", "response.output_text.done"]
