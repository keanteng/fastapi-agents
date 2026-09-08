from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.documents.extraction import ALLOWED_EXTENSIONS


class UploadNotFoundError(Exception):
    pass


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
        "created_at": datetime.now(UTC).isoformat(),
    }
    _meta_path(root, upload_id).write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return meta


def get_upload(upload_id: str) -> dict:
    """Return ``{path, meta}`` for a stored upload, raising if absent."""
    root = _upload_root()
    file_path = root / upload_id
    meta_file = _meta_path(root, upload_id)
    if not file_path.is_file() or not meta_file.is_file():
        raise UploadNotFoundError(f"upload {upload_id} does not exist")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    return {"path": file_path, "meta": meta}
