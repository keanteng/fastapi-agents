from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core import metrics
from app.runs.events import RunEvent, cancelled_data, ping_data, step_data
from app.runs.models import (
    RunRecord,
    RunStatus,
    TERMINAL_STATUSES,
)
from app.runs.store import RunStore

logger = logging.getLogger(__name__)

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


class QueueFullError(Exception):
    """Raised when the bounded run queue is at capacity."""

    def __init__(self, max_size: int) -> None:
        super().__init__(f"run queue is full (max {max_size})")
        self.max_size = max_size


class RunRegistry:
    """Live run registry with write-through persistence and a worker pool.

    All in-memory mutations happen under a single lock. When a ``store`` is
    supplied, every state change is written through to the database. When
    ``max_concurrent`` is positive, runs are dispatched to a bounded worker
    pool instead of spawning an unbounded task per request.
    """

    def __init__(
        self,
        store: RunStore | None = None,
        *,
        max_concurrent: int = 0,
        queue_max: int = 0,
    ) -> None:
        self._records: dict[str, RunRecord] = {}
        self.lock = asyncio.Lock()
        self._store = store
        self._max_concurrent = max_concurrent
        self._queue_max = queue_max
        self._queue: asyncio.Queue[tuple[RunRecord, Any, Any]] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._closing = False

    def register(self, record: RunRecord) -> None:
        """Insert a pre-built record (tests and direct callers)."""
        self._records[record.run_id] = record

    async def create(self, request: Any, container: Any) -> RunRecord:
        """Create a pending run and dispatch it.

        With ``max_concurrent <= 0`` the run starts as a dedicated task (the
        historical behaviour); otherwise it is queued for the worker pool.
        """
        record = RunRecord(
            run_id=uuid.uuid4().hex,
            agent=request.agent,
            conversation_id=request.conversation_id,
        )
        record.input = request.input
        record.tools = request.tools
        record.capabilities = request.capabilities
        record.max_steps = request.max_steps
        record.idempotency_key = getattr(request, "idempotency_key", None)
        record.metadata = request.metadata
        record.request = request
        async with self.lock:
            self._records[record.run_id] = record
        await self.persist(record)

        if self._max_concurrent > 0:
            await self._enqueue(record, container, request)
        else:
            from app.runs.runner import execute_run  # local import avoids a cycle

            task = asyncio.create_task(execute_run(record, self, container, request))
            record.task = task
        return record

    async def get(self, run_id: str) -> RunRecord:
        async with self.lock:
            record = self._records.get(run_id)
        if record is not None:
            return record
        if self._store is not None:
            stored = await self._store.get(run_id)
            if stored is not None:
                return stored
        raise RunNotFoundError(run_id)

    async def list(self) -> list[RunRecord]:
        async with self.lock:
            memory = list(self._records.values())
        if self._store is None:
            records = memory
        else:
            by_id = {record.run_id: record for record in await self._store.list()}
            by_id.update({record.run_id: record for record in memory})
            records = list(by_id.values())
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    async def persist(self, record: RunRecord) -> None:
        """Write the record snapshot to the store, if one is configured."""
        if self._store is None:
            return
        try:
            await self._store.save(record)
        except Exception:  # noqa: BLE001 - persistence must not kill a run
            logger.exception("failed to persist run %s", record.run_id)

    async def reconcile(self) -> int:
        """Fail runs orphaned by a previous process (called on startup)."""
        if self._store is None:
            return 0
        return await self._store.reconcile_stale()

    async def find_by_idempotency_key(self, key: str) -> RunRecord | None:
        if self._store is None or not key:
            return None
        async with self.lock:
            for record in self._records.values():
                if record.idempotency_key == key:
                    return record
        return await self._store.find_by_idempotency_key(key)

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
                metrics.observe_run_status(record.agent, RunStatus.CANCELLED.value)
        if task is not None:
            task.cancel()
        await self.persist(record)
        return record

    async def shutdown(self) -> None:
        """Cancel every in-flight run and stop the worker pool."""
        self._closing = True
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
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            try:
                await worker
            except asyncio.CancelledError:
                pass
        self._workers.clear()

    # ------------------------------------------------------------------ #
    # Worker pool
    # ------------------------------------------------------------------ #

    def _ensure_workers(self) -> None:
        if self._max_concurrent <= 0 or self._workers:
            return
        loop = asyncio.get_running_loop()
        for _ in range(self._max_concurrent):
            self._workers.append(loop.create_task(self._worker_loop()))

    async def _enqueue(self, record: RunRecord, container: Any, request: Any) -> None:
        self._ensure_workers()
        if 0 < self._queue_max <= self._queue.qsize():
            async with self.lock:
                self._records.pop(record.run_id, None)
            if self._store is not None:
                await self._store.delete(record.run_id)
            raise QueueFullError(self._queue_max)
        self._queue.put_nowait((record, container, request))

    async def _worker_loop(self) -> None:
        from app.runs.runner import execute_run

        while not self._closing:
            record, container, request = await self._queue.get()
            try:
                if record.status in TERMINAL_STATUSES:
                    continue
                record.task = asyncio.current_task()
                await execute_run(record, self, container, request)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad run must not kill a worker
                logger.exception(
                    "worker failed on run %s", getattr(record, "run_id", "?")
                )
            finally:
                if hasattr(record, "task"):
                    record.task = None
                self._queue.task_done()

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
        record.seq_counter += 1
        sequence = record.seq_counter
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
        maxlen = log.maxlen
        if maxlen is None:
            log.append(event)
            return
        if event.terminal:
            while len(log) >= maxlen and not log[0].terminal:
                log.popleft()
        elif len(log) >= maxlen:
            log.popleft()
        log.append(event)

    async def add_step(self, record: RunRecord, step: Any) -> None:
        """Append a step to the record and emit its ``run.step`` event."""
        async with self.lock:
            step.index = len(record.steps) + 1
            record.steps.append(step)
            self._emit_locked(record, "run.step", step_data(step))
        await self.persist(record)

    async def add_progress(self, record: RunRecord, message: str) -> None:
        """Record a transient pipeline progress line as a ``progress`` step.

        Long-running tools (e.g. document compliance) call this to stream a
        lightweight, human-readable status tick into the ``run.step`` stream.
        """
        from app.runs.models import RunStep

        now = _now()
        step = RunStep(
            index=0,
            type="progress",
            name="progress",
            summary=message[:200],
            result=None,
            started_at=now,
            finished_at=now,
        )
        await self.add_step(record, step)

    async def emit_ping(self, record: RunRecord) -> RunEvent:
        """Build a keepalive ping event (not stored in the event log)."""
        async with self.lock:
            record.seq_counter += 1
            sequence = record.seq_counter
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

    async def claim_subscriber(self, run_id: str) -> tuple[RunRecord, list[RunEvent]]:
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
