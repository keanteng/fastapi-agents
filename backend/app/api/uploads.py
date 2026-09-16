from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel

from app.api.errors import AppError
from app.core.security import owner_for_request
from app.documents.storage import (
    UploadForbiddenError,
    UploadNotFoundError,
    UploadTooLargeError,
    get_upload,
    save_upload,
)

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


class UploadOut(BaseModel):
    upload_id: str
    file_name: str
    content_type: str | None = None
    size: int
    created_at: datetime


@router.post("", response_model=UploadOut, status_code=201)
async def upload_file(request: Request, file: UploadFile = File(...)) -> UploadOut:
    """Upload a document for later analysis (compliance checks etc.).

    Bytes are stored once locally under ``UPLOAD_DIR``, keyed by sha1; the
    returned ``upload_id`` is passed to agent document tools.
    """
    file_name = file.filename or ""
    if not file_name or "." not in file_name:
        raise AppError(
            422, "invalid_file_name", "a file name with an extension is required"
        )
    data = await file.read()
    if not data:
        raise AppError(422, "empty_file", "the uploaded file is empty")
    try:
        meta = save_upload(
            file_name=file_name,
            content_type=file.content_type,
            data=data,
            owner=owner_for_request(request),
        )
    except ValueError as exc:
        raise AppError(422, "unsupported_file_type", str(exc)) from None
    except UploadTooLargeError as exc:
        raise AppError(413, "file_too_large", str(exc)) from None
    return UploadOut(**meta)


@router.get("/{upload_id}", response_model=UploadOut)
async def get_upload_meta(upload_id: str, request: Request) -> UploadOut:
    """Return metadata for a previously uploaded file."""
    try:
        record = get_upload(upload_id, owner=owner_for_request(request))
    except UploadNotFoundError:
        raise AppError(
            404, "upload_not_found", f"upload {upload_id} does not exist"
        ) from None
    except UploadForbiddenError:
        raise AppError(
            403, "upload_forbidden", f"upload {upload_id} belongs to another caller"
        ) from None
    return UploadOut(**record["meta"])
