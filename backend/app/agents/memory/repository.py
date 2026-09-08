from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.memory.models import Conversation, Message

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

    async def list_summaries(self) -> list[dict]:
        """Return conversation summaries ordered by most recent activity.

        Each summary has ``conversation_id``, ``created_at``, ``updated_at``,
        ``message_count`` and ``preview`` (the first user message text).
        """
        last_at = func.coalesce(func.max(Message.created_at), Conversation.created_at)
        rows = await self._session.execute(
            select(
                Conversation.id,
                Conversation.created_at,
                func.count(Message.id).label("message_count"),
                last_at.label("updated_at"),
            )
            .select_from(Conversation)
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .group_by(Conversation.id, Conversation.created_at)
            .order_by(last_at.desc(), Conversation.created_at.desc())
        )
        summaries: list[dict] = []
        conversation_ids: list[str] = []
        for row in rows:
            conversation_ids.append(row.id)
            summaries.append(
                {
                    "conversation_id": row.id,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "message_count": row.message_count or 0,
                }
            )
        if conversation_ids:
            preview_rows = await self._session.execute(
                select(Message.conversation_id, Message.payload)
                .where(
                    Message.conversation_id.in_(conversation_ids),
                    Message.seq == 0,
                )
            )
            previews = {
                conv_id: self._preview_text(payload)
                for conv_id, payload in preview_rows
            }
            for summary in summaries:
                summary["preview"] = previews.get(summary["conversation_id"])
        return summaries

    async def get_conversation(
        self, conversation_id: str
    ) -> tuple[datetime, list[ModelMessage]] | None:
        """Return ``(created_at, messages)`` for a conversation, or ``None``."""
        conv = await self._session.get(Conversation, conversation_id)
        if conv is None:
            return None
        messages = await self.get(conversation_id)
        return conv.created_at, messages

    @staticmethod
    def _preview_text(payload: dict | None) -> str | None:
        """Extract the first user text from a persisted message payload."""
        if not payload:
            return None
        try:
            messages = _load([payload])
        except Exception:
            return None
        if not messages:
            return None
        from app.agents.memory.serialize import to_dto

        for message in to_dto(messages):
            for part in message.parts:
                if part.role == "user" and part.content:
                    text = part.content.strip()
                    return text[:140] + ("…" if len(text) > 140 else "")
        return None
