from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_session_maker
from app.runs.models import ErrorBody, RunRecord, RunStatus
from app.runs.orm import RunRow, record_from_row, row_from_record

_STALE_STATUSES = (RunStatus.PENDING.value, RunStatus.RUNNING.value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunStore:
    """Persistence boundary for runs.

    ``RunRegistry`` keeps the live, in-memory record for in-flight runs; this
    store is written through on every state change so runs survive restarts and
    can be listed/queried after the process that executed them is gone.
    """

    def __init__(
        self,
        session_factory: Callable[[], async_sessionmaker[AsyncSession]] | None = None,
    ) -> None:
        self._session_factory = session_factory or get_session_maker
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        """A serialised session: one DB operation at a time per process.

        A run is mutated from several coroutines (request handlers, worker
        tasks). Serialising here avoids concurrent checkouts of the same
        pooled connection, which is what makes SQLite tests flaky, and keeps
        write ordering deterministic.
        """
        async with self._lock:
            async with self._session_factory()() as session:
                yield session

    async def save(self, record: RunRecord) -> None:
        async with self._session() as session:
            await session.merge(row_from_record(record))
            await session.commit()

    async def get(self, run_id: str) -> RunRecord | None:
        async with self._session() as session:
            row = await session.get(RunRow, run_id)
            return record_from_row(row) if row is not None else None

    async def list(self, limit: int = 200) -> list[RunRecord]:
        async with self._session() as session:
            rows = await session.scalars(
                select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)
            )
            return [record_from_row(row) for row in rows]

    async def find_by_idempotency_key(self, key: str) -> RunRecord | None:
        if not key:
            return None
        async with self._session() as session:
            row = await session.scalars(
                select(RunRow)
                .where(RunRow.idempotency_key == key)
                .order_by(RunRow.created_at.desc())
                .limit(1)
            )
            found = row.first()
            return record_from_row(found) if found is not None else None

    async def delete(self, run_id: str) -> None:
        async with self._session() as session:
            await session.execute(delete(RunRow).where(RunRow.run_id == run_id))
            await session.commit()

    async def reconcile_stale(self) -> int:
        """Mark runs left ``pending``/``running`` by a dead process as failed."""
        async with self._session() as session:
            rows = await session.scalars(
                select(RunRow).where(RunRow.status.in_(_STALE_STATUSES))
            )
            stale = list(rows)
            for row in stale:
                row.status = RunStatus.FAILED.value
                row.finished_at = _now()
                row.error = ErrorBody(
                    code="interrupted",
                    message="run was interrupted by a server restart",
                    run_id=row.run_id,
                ).model_dump(mode="json")
            await session.commit()
            return len(stale)
