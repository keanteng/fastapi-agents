from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.documents.extraction import ALLOWED_EXTENSIONS


class UploadNotFoundError(Exception):
    pass


class UploadForbiddenError(Exception):
    """The caller does not own the requested upload."""


class UploadTooLargeError(Exception):
    pass


def _upload_root() -> Path:
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _meta_path(root: Path, upload_id: str) -> Path:
    return root / f"{upload_id}.json"


def save_upload(
    *,
    file_name: str,
    content_type: str | None,
    data: bytes,
    owner: str | None = None,
) -> dict:
    """Store upload bytes under a sha1 id and return its metadata record."""
    size = len(data)
    if size > settings.upload_max_bytes:
        raise UploadTooLargeError(
            f"file is {size} bytes; limit is {settings.upload_max_bytes}"
        )
    ext = file_name.rsplit(".", maxsplit=1)[-1].lower() if "." in file_name else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"unsupported file extension '.{ext}'")

    upload_id = hashlib.sha1(data).hexdigest()
    root = _upload_root()
    file_path = root / upload_id
    if not file_path.exists():
        file_path.write_bytes(data)
    meta = {
        "upload_id": upload_id,
        "file_name": file_name,
        "content_type": content_type,
        "size": size,
        "owner": owner,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _meta_path(root, upload_id).write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return meta


def get_upload(upload_id: str, *, owner: str | None = None) -> dict:
    """Return ``{path, meta}`` for a stored upload, raising if absent.

    When ``owner`` is provided, the stored upload must belong to that owner
    (an upload with no recorded owner is treated as shared/legacy).
    """
    root = _upload_root()
    file_path = root / upload_id
    meta_file = _meta_path(root, upload_id)
    if not file_path.is_file() or not meta_file.is_file():
        raise UploadNotFoundError(f"upload {upload_id} does not exist")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    stored_owner = meta.get("owner")
    if owner is not None and stored_owner not in (None, owner):
        raise UploadForbiddenError(f"upload {upload_id} belongs to another caller")
    return {"path": file_path, "meta": meta}


def iter_uploads() -> list[tuple[Path, dict]]:
    """Return every stored upload as ``(meta_path, meta)`` pairs."""
    root = _upload_root()
    uploads: list[tuple[Path, dict]] = []
    for meta_file in root.glob("*.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        uploads.append((meta_file, meta))
    return uploads


def delete_upload(upload_id: str) -> None:
    """Remove an upload's bytes and metadata (best-effort)."""
    root = _upload_root()
    (root / upload_id).unlink(missing_ok=True)
    _meta_path(root, upload_id).unlink(missing_ok=True)


def purge_expired_uploads(ttl_seconds: int, *, now: datetime | None = None) -> int:
    """Delete uploads older than ``ttl_seconds``; returns the count removed."""
    if ttl_seconds <= 0:
        return 0
    reference = (now or datetime.now(UTC)).timestamp()
    removed = 0
    for meta_file, meta in iter_uploads():
        created_at = meta.get("created_at")
        try:
            created = datetime.fromisoformat(str(created_at)).timestamp()
        except (TypeError, ValueError):
            continue
        if reference - created > ttl_seconds:
            delete_upload(str(meta.get("upload_id") or meta_file.stem))
            removed += 1
    return removed
