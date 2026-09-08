from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.agents.memory.repository import MemoryRepository
from app.core.db import get_session_maker


async def load_history(conversation_id: str) -> list[Any]:
    """Load persisted message history for a conversation."""
    session = get_session_maker()()
    try:
        return await MemoryRepository(session).get(conversation_id)
    finally:
        await session.close()


async def persist_history(conversation_id: str, messages: Sequence[Any]) -> None:
    """Persist a full turn of messages for a conversation (replaces history)."""
    session = get_session_maker()()
    try:
        await MemoryRepository(session).set(conversation_id, messages)
        await session.commit()
    finally:
        await session.close()
