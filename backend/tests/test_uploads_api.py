from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.fixture
def upload_dir(tmp_path, monkeypatch) -> str:
    path = tmp_path / "uploads"
    monkeypatch.setattr(settings, "upload_dir", str(path))
    return str(path)


def test_upload_roundtrip(client, upload_dir) -> None:
    content = b"this is a plain text upload"
    r = client.post(
        "/api/v1/uploads",
        files={"file": ("note.txt", content, "text/plain")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["file_name"] == "note.txt"
    assert body["size"] == len(content)
    upload_id = body["upload_id"]

    meta = client.get(f"/api/v1/uploads/{upload_id}")
    assert meta.status_code == 200
    assert meta.json()["upload_id"] == upload_id

    # Same bytes dedupe to the same id.
    again = client.post(
        "/api/v1/uploads",
        files={"file": ("note-copy.txt", content, "text/plain")},
    )
    assert again.status_code == 201
    assert again.json()["upload_id"] == upload_id


def test_upload_rejects_bad_extension(client, upload_dir) -> None:
    r = client.post(
        "/api/v1/uploads",
        files={"file": ("script.exe", b"MZ...", "application/octet-stream")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unsupported_file_type"


def test_upload_rejects_empty(client, upload_dir) -> None:
    r = client.post(
        "/api/v1/uploads",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "empty_file"


def test_upload_unknown_404(client, upload_dir) -> None:
    r = client.get("/api/v1/uploads/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "upload_not_found"


def test_upload_requires_extension(client, upload_dir) -> None:
    r = client.post(
        "/api/v1/uploads",
        files={"file": ("noextension", b"x", "text/plain")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_file_name"
