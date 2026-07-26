from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.memory.models import Conversation, Message

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter

_CAPACITY: Final[int] = 100


def _dump(messages: Iterable[ModelMessage]) -> list[dict]:
    return ModelMessagesTypeAdapter.dump_python(list(messages), mode="json")  # type: ignore[misc]


def _load(payloads: Sequence[dict]) -> list[ModelMessage]:
    if not payloads:
        return []
    return list(ModelMessagesTypeAdapter.validate_python(list(payloads)))  # type: ignore[misc]


class MemoryRepository:
    """Conversation/message persistence on top of an ``AsyncSession``."""

    def __init__(self, session: AsyncSession, capacity: int = _CAPACITY) -> None:
        self._session = session
        self._capacity = capacity

    async def _ensure_conversation(self, conversation_id: str) -> None:
        existing = await self._session.get(Conversation, conversation_id)
        if existing is None:
            self._session.add(Conversation(id=conversation_id))

    async def exists(self, conversation_id: str) -> bool:
        conv = await self._session.get(Conversation, conversation_id)
        return conv is not None

    async def get(self, conversation_id: str) -> list[ModelMessage]:
        rows = await self._session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.seq)
        )
        payload = [row.payload for row in rows]
        return _load(payload)

    async def count(self, conversation_id: str) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation_id)
            )
            or 0
        )

    async def ensure(self, conversation_id: str) -> None:
        await self._ensure_conversation(conversation_id)
        await self._session.flush()

    async def set(
        self,
        conversation_id: str,
        messages: Iterable[ModelMessage] | Sequence[ModelMessage],
    ) -> list[ModelMessage]:
        msg_list = list(messages)[-self._capacity :]
        await self._ensure_conversation(conversation_id)
        await self._session.execute(
            delete(Message).where(Message.conversation_id == conversation_id)
        )
        for seq, msg in enumerate(msg_list):
            self._session.add(
                Message(
                    conversation_id=conversation_id,
                    seq=seq,
                    kind=type(msg).__name__,
                    payload=_dump([msg])[0],
                )
            )
        await self._session.flush()
        return msg_list

    async def append(
        self, conversation_id: str, messages: Iterable[ModelMessage]
    ) -> list[ModelMessage]:
        incoming = list(messages)
        if not incoming:
            return await self.get(conversation_id)
        await self._ensure_conversation(conversation_id)
        current_count = await self.count(conversation_id)
        for offset, msg in enumerate(incoming):
            self._session.add(
                Message(
                    conversation_id=conversation_id,
                    seq=current_count + offset,
                    kind=type(msg).__name__,
                    payload=_dump([msg])[0],
                )
            )
        await self._session.flush()
        all_msgs = await self.get(conversation_id)
        if len(all_msgs) > self._capacity:
            await self.set(conversation_id, all_msgs)
            all_msgs = all_msgs[-self._capacity :]
        return all_msgs

    async def clear(self, conversation_id: str) -> bool:
        conv = await self._session.get(Conversation, conversation_id)
        if conv is None:
            return False
        await self._session.delete(conv)
        await self._session.flush()
        return True

    async def list_ids(self) -> list[str]:
        rows = await self._session.scalars(select(Conversation.id))
        return list(rows)
