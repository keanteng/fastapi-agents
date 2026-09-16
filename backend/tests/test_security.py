from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import get_rate_limiter
from app.documents.storage import (
    UploadForbiddenError,
    get_upload,
    purge_expired_uploads,
    save_upload,
)


def test_runs_require_api_key_when_auth_enabled(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "api_keys", "secret")

    unauthorized = client.post(
        "/api/v1/runs", json={"agent": "generalist", "input": "hi"}
    )
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"

    wrong = client.post(
        "/api/v1/runs",
        json={"agent": "generalist", "input": "hi"},
        headers={"X-API-Key": "nope"},
    )
    assert wrong.status_code == 401

    accepted = client.post(
        "/api/v1/runs",
        json={"agent": "generalist", "input": "hi"},
        headers={"X-API-Key": "secret"},
    )
    assert accepted.status_code == 202


def test_health_stays_open_when_auth_enabled(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "api_keys", "secret")
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_rate_limit_returns_429_with_retry_after(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_requests", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    get_rate_limiter().reset()

    assert client.get("/api/v1/agents").status_code == 200
    assert client.get("/api/v1/agents").status_code == 200
    limited = client.get("/api/v1/agents")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert "Retry-After" in limited.headers


def test_upload_ownership_is_enforced(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    uploaded = client.post(
        "/api/v1/uploads",
        files={"file": ("a.txt", b"hello", "text/plain")},
        headers={"X-API-Key": "owner-a"},
    )
    assert uploaded.status_code == 201
    upload_id = uploaded.json()["upload_id"]

    allowed = client.get(
        f"/api/v1/uploads/{upload_id}", headers={"X-API-Key": "owner-a"}
    )
    assert allowed.status_code == 200

    denied = client.get(
        f"/api/v1/uploads/{upload_id}", headers={"X-API-Key": "owner-b"}
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "upload_forbidden"


def test_get_upload_rejects_other_owner(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    meta = save_upload(
        file_name="a.txt", content_type="text/plain", data=b"hello", owner="me"
    )
    with pytest.raises(UploadForbiddenError):
        get_upload(meta["upload_id"], owner="someone-else")


def test_purge_expired_uploads_removes_old_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    meta = save_upload(file_name="a.txt", content_type="text/plain", data=b"hello")
    upload_id = meta["upload_id"]
    meta_path = tmp_path / f"{upload_id}.json"
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    payload["created_at"] = "2000-01-01T00:00:00+00:00"
    meta_path.write_text(json.dumps(payload), encoding="utf-8")

    assert purge_expired_uploads(ttl_seconds=60) == 1
    assert not (tmp_path / upload_id).exists()
    assert not meta_path.exists()


def test_purge_disabled_when_ttl_non_positive(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    save_upload(file_name="a.txt", content_type="text/plain", data=b"hello")
    assert purge_expired_uploads(ttl_seconds=0) == 0
