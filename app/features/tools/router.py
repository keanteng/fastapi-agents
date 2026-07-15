"""Tools slice routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.features.tools.schemas import ToolsRequest, ToolsResponse
from app.features.tools.service import run_with_tools

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.post("", response_model=ToolsResponse)
async def tools(req: ToolsRequest) -> ToolsResponse:
    output, usage = await run_with_tools(req.user_prompt)
    return ToolsResponse(output=output, usage=usage)