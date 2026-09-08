from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.errors import AppError, register_error_handlers


class Item(BaseModel):
    x: int


def _make_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/validate")
    async def validate(body: Item) -> dict:
        return {"ok": body.x}

    @app.get("/app-error")
    async def app_error() -> None:
        raise AppError(404, "run_not_found", "run abc does not exist", run_id="abc")

    @app.get("/internal")
    async def internal() -> None:
        raise RuntimeError("boom")

    return app


def test_app_error_envelope() -> None:
    client = TestClient(_make_app())
    response = client.get("/app-error")
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "run_not_found",
            "message": "run abc does not exist",
            "details": None,
            "run_id": "abc",
        }
    }


def test_validation_error_envelope() -> None:
    client = TestClient(_make_app())
    response = client.post("/validate", json={})
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == "validation_error"
    assert error["run_id"] is None
    assert any(entry["loc"] == ["body", "x"] for entry in error["details"])


def test_internal_error_envelope() -> None:
    client = TestClient(_make_app(), raise_server_exceptions=False)
    response = client.get("/internal")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "internal server error",
            "details": None,
            "run_id": None,
        }
    }


def test_real_app_404_envelope(client) -> None:
    r = client.get("/api/v1/runs/nope")
    body = r.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details", "run_id"}
    assert body["error"]["code"] == "run_not_found"


def test_real_app_unknown_agent_envelope(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "ghost", "input": "hi"})
    body = r.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "unknown_agent"
    assert body["error"]["run_id"] is None


def test_real_app_validation_envelope(client) -> None:
    r = client.post("/api/v1/runs", json={"agent": "generalist", "input": ""})
    body = r.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]
