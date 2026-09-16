from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.runs.models import (
    RunArtifact,
    RunRecord,
    RunStatus,
    RunStep,
    RunUsage,
)
from app.runs.registry import QueueFullError, RunRegistry
from app.runs.store import RunStore


def _record(run_id: str = "run-1", status: RunStatus = RunStatus.PENDING) -> RunRecord:
    now = datetime.now(timezone.utc)
    record = RunRecord(run_id=run_id, agent="generalist", conversation_id="c1")
    record.input = "hello"
    record.tools = ["calculator"]
    record.capabilities = ["thinking"]
    record.max_steps = 8
    record.metadata = {"trace": "abc"}
    record.idempotency_key = "idem-1"
    record.status = status
    record.started_at = now
    record.steps = [
        RunStep(
            index=1,
            type="tool_call",
            name="calculator",
            summary="1+1",
            result="2",
            started_at=now,
            finished_at=now,
        )
    ]
    record.artifacts = [RunArtifact(name="output", kind="text", data="done")]
    record.usage = RunUsage(input_tokens=3, output_tokens=4, requests=1, tool_calls=1)
    record.note = "note"
    return record


async def test_store_roundtrip_preserves_record() -> None:
    store = RunStore()
    record = _record(status=RunStatus.COMPLETED)
    record.finished_at = datetime.now(timezone.utc)
    await store.save(record)

    loaded = await store.get("run-1")
    assert loaded is not None
    assert loaded.agent == "generalist"
    assert loaded.status == RunStatus.COMPLETED
    assert loaded.conversation_id == "c1"
    assert loaded.input == "hello"
    assert loaded.tools == ["calculator"]
    assert loaded.capabilities == ["thinking"]
    assert loaded.max_steps == 8
    assert loaded.metadata == {"trace": "abc"}
    assert loaded.idempotency_key == "idem-1"
    assert loaded.usage is not None and loaded.usage.requests == 1
    assert loaded.artifacts[0].data == "done"
    assert [step.name for step in loaded.steps] == ["calculator"]
    assert loaded.started_at is not None and loaded.started_at.tzinfo is not None


async def test_store_upsert_updates_existing_row() -> None:
    store = RunStore()
    record = _record()
    await store.save(record)
    record.status = RunStatus.COMPLETED
    await store.save(record)
    loaded = await store.get("run-1")
    assert loaded is not None and loaded.status == RunStatus.COMPLETED


async def test_store_idempotency_lookup() -> None:
    store = RunStore()
    await store.save(_record())
    found = await store.find_by_idempotency_key("idem-1")
    assert found is not None and found.run_id == "run-1"
    assert await store.find_by_idempotency_key("missing") is None


async def test_reconcile_marks_stale_runs_failed() -> None:
    store = RunStore()
    await store.save(_record("stale", status=RunStatus.RUNNING))
    await store.save(_record("done", status=RunStatus.COMPLETED))

    assert await store.reconcile_stale() == 1
    stale = await store.get("stale")
    assert stale is not None and stale.status == RunStatus.FAILED
    assert stale.error is not None and stale.error.code == "interrupted"
    done = await store.get("done")
    assert done is not None and done.status == RunStatus.COMPLETED


async def test_registry_falls_back_to_store_after_restart() -> None:
    store = RunStore()
    await store.save(_record("persisted", status=RunStatus.COMPLETED))

    fresh_registry = RunRegistry(store)
    loaded = await fresh_registry.get("persisted")
    assert loaded.run_id == "persisted"
    assert loaded.status == RunStatus.COMPLETED

    listed = await fresh_registry.list()
    assert [record.run_id for record in listed] == ["persisted"]


async def test_registry_find_by_idempotency_key() -> None:
    store = RunStore()
    registry = RunRegistry(store)
    await store.save(_record("idem-run"))
    found = await registry.find_by_idempotency_key("idem-1")
    assert found is not None and found.run_id == "idem-run"


async def test_store_delete_removes_row() -> None:
    store = RunStore()
    await store.save(_record("gone"))
    await store.delete("gone")
    assert await store.get("gone") is None


def test_queue_full_raises_and_cleans_memory() -> None:
    import types

    async def _go() -> None:
        registry = RunRegistry(max_concurrent=1, queue_max=1)
        # Pretend the pool already started so ``_ensure_workers`` does not spawn
        # real tasks; then fill the (capacity-1) queue.
        registry._workers = [object()]  # type: ignore[list-item]
        registry._queue.put_nowait(("placeholder", object(), object()))
        request = types.SimpleNamespace(
            agent="generalist",
            input="hi",
            conversation_id=None,
            message_history=None,
            tools=None,
            capabilities=None,
            max_steps=8,
            metadata=None,
            idempotency_key=None,
        )
        with pytest.raises(QueueFullError):
            await registry.create(request, container=object())
        assert registry._records == {}

    asyncio.run(_go())


def test_create_run_is_idempotent_with_key(client) -> None:
    payload = {"agent": "generalist", "input": "hi", "idempotency_key": "same-key"}
    first = client.post("/api/v1/runs", json=payload)
    second = client.post("/api/v1/runs", json=payload)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]


async def test_worker_pool_executes_run(agent_model) -> None:
    import types

    from pydantic_ai.models.test import TestModel

    from app.core.container import get_container

    agent_model(TestModel(call_tools=[], custom_output_text="hi"))
    container = get_container()
    registry = RunRegistry(max_concurrent=2, queue_max=4)
    request = types.SimpleNamespace(
        agent="generalist",
        input="hello",
        conversation_id=None,
        message_history=None,
        tools=None,
        capabilities=None,
        max_steps=4,
        metadata=None,
        idempotency_key=None,
    )
    record = await registry.create(request, container)
    assert record.task is None
    for _ in range(200):
        if record.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            break
        await asyncio.sleep(0.01)
    assert record.status == RunStatus.COMPLETED
    await registry.shutdown()
