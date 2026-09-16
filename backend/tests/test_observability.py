from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.runs.runner import classify_error


def test_metrics_endpoint_exposes_prometheus(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "agents_runs_active" in response.text


def test_metrics_endpoint_can_be_disabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    assert client.get("/metrics").status_code == 404


def test_classify_error_taxonomy() -> None:
    assert classify_error(ValueError("boom"))[0] == "model_error"
    assert classify_error(RuntimeError("HTTP 429 rate limit"))[0] == "model_rate_limited"
    assert classify_error(RuntimeError("invalid api key"))[0] == "model_auth_error"
    assert classify_error(RuntimeError("maximum context length exceeded"))[0] == (
        "context_length_exceeded"
    )


def test_classify_tool_retry_error() -> None:
    from pydantic_ai.exceptions import ToolRetryError
    from pydantic_ai.messages import RetryPromptPart

    exc = ToolRetryError(RetryPromptPart(content="Tool exceeded max retries count"))
    code, message = classify_error(exc)
    assert code == "tool_error"
    assert "tool call failed after retries" in message


def test_fallback_model_absent_by_default(monkeypatch) -> None:
    from app.core.model import _build_fallback_model

    monkeypatch.setattr(settings, "model_fallback", None)
    assert _build_fallback_model() is None


def test_fallback_model_built_when_configured(monkeypatch) -> None:
    from app.core.model import _build_fallback_model

    monkeypatch.setattr(settings, "model_fallback", "some-model")
    monkeypatch.setattr(settings, "model_fallback_base_url", "https://example.com/v1")
    monkeypatch.setattr(settings, "model_fallback_api_key", "key")
    assert _build_fallback_model() is not None
