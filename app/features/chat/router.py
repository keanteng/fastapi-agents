"""Chat slice routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.features.chat.schemas import ChatRequest, ChatResponse
from app.features.chat.service import run_chat, stream_chat

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _resolve_conversation_id(req: ChatRequest) -> str:
    """Return the client-supplied id or mint a server-generated one.

    The chat slice is stateless and never persists, but echoing a stable id
    lets a client reuse it for later memory endpoints.
    """
    return req.conversation_id or uuid.uuid4().hex


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    output, _messages, usage = await run_chat(req.user_prompt)
    return ChatResponse(
        output=output,
        conversation_id=_resolve_conversation_id(req),
        usage=usage,
    )


@router.post("/stream")
async def chat_stream(req: ChatRequest) -> EventSourceResponse:
    conversation_id = _resolve_conversation_id(req)

    async def gen():
        yield {"event": "conversation_id", "data": conversation_id}
        async for chunk in stream_chat(req.user_prompt):
            yield {"data": chunk}

    return EventSourceResponse(gen())