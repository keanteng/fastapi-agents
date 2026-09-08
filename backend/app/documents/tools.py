from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.documents import extraction as extraction_mod
from app.documents.service import ComplianceService, build_compliance_service
from app.documents.storage import get_upload

Emit = Callable[[str], Awaitable[None]]


def make_document_tools(
    *,
    emit: Emit | None = None,
    service: ComplianceService | None = None,
) -> dict[str, Callable]:
    """Build the document tools the generalist can call.

    ``emit`` optionally streams ``run.step`` progress lines; pass it from the
    run runner to get live progress inside the transcript.
    """

    async def _progress(message: str) -> None:
        if emit is not None:
            await emit(message)

    async def document_text(upload_id: str) -> str:
        """Extract and return the readable text of an uploaded file so you can answer questions about its contents."""
        await _progress("Extracting document text…")
        record = get_upload(upload_id)
        path = record["path"]
        file_name = record["meta"].get("file_name", "document")
        await _progress(f"Reading {file_name}…")
        document = await asyncio.to_thread(extraction_mod.extract_text, path, file_name)
        text = document.full_text
        return text[:20000] + ("\n…[truncated]" if len(text) > 20000 else "") or (
            "(no extractable text found)"
        )

    async def check_compliance(upload_id: str) -> str:
        """Run a PII / sensitive-data compliance check on an uploaded file and return a JSON verdict with the reasons."""
        svc = service or build_compliance_service()
        report = await svc.assess(upload_id, emit=_progress)
        return report.model_dump_json()

    return {"document_text": document_text, "check_compliance": check_compliance}
