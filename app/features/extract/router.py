from __future__ import annotations

from fastapi import APIRouter

from app.features.extract.schemas import ExtractRequest, ExtractResponse
from app.features.extract.service import extract

router = APIRouter(prefix="/api/v1/extract", tags=["extract"])


@router.post("", response_model=ExtractResponse)
async def extract_entities(req: ExtractRequest) -> ExtractResponse:
    result, usage = await extract(req.text)
    return ExtractResponse(result=result, usage=usage)
