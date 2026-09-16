from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """A small async-safe, bounded, TTL cache.

    Entries expire after ``ttl`` seconds; the least-recently-used entry is
    evicted once ``max_entries`` is exceeded. Set ``max_entries <= 0`` to
    disable caching entirely.
    """

    def __init__(self, *, ttl: float, max_entries: int) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._ttl > 0 and self._max_entries > 0

    async def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    async def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        async with self._lock:
            self._data[key] = (time.monotonic() + self._ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()
