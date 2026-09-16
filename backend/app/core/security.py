from __future__ import annotations

import time

from fastapi import Request

from app.api.errors import AppError
from app.core.config import settings

API_KEY_HEADER = "X-API-Key"
ANONYMOUS = "anonymous"


def request_api_key(request: Request) -> str | None:
    """The presented API key, if any (no validation)."""
    return request.headers.get(API_KEY_HEADER) or None


def client_id(request: Request) -> str:
    """A stable identity for rate limiting: API key, else client IP."""
    key = request_api_key(request)
    if key:
        return f"key:{key}"
    if request.client is not None and request.client.host:
        return f"ip:{request.client.host}"
    return ANONYMOUS


def owner_for_request(request: Request) -> str | None:
    """The upload owner: the authenticated key, else ``None`` (anonymous)."""
    return request_api_key(request)


async def require_api_key(request: Request) -> str | None:
    """FastAPI dependency enforcing ``X-API-Key`` when auth is enabled."""
    if not settings.auth_enabled:
        return None
    key = request_api_key(request)
    if not key or key not in settings.api_key_set:
        raise AppError(
            401,
            "unauthorized",
            "a valid X-API-Key header is required",
        )
    return key


class TokenBucketLimiter:
    """In-process token-bucket rate limiter keyed by client identity."""

    def __init__(self, capacity: int, window_seconds: float) -> None:
        self._capacity = max(1, capacity)
        self._refill_per_second = self._capacity / max(1.0, window_seconds)
        self._tokens: dict[str, float] = {}
        self._updated: dict[str, float] = {}

    def configure(self, capacity: int, window_seconds: float) -> None:
        self._capacity = max(1, capacity)
        self._refill_per_second = self._capacity / max(1.0, window_seconds)

    def _refill(self, key: str, now: float) -> float:
        last = self._updated.get(key, now)
        tokens = min(self._capacity, self._tokens.get(key, self._capacity))
        tokens += (now - last) * self._refill_per_second
        self._tokens[key] = tokens
        self._updated[key] = now
        return tokens

    def allow(self, key: str) -> tuple[bool, float]:
        """Consume one token; returns ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        tokens = self._refill(key, now)
        if tokens >= 1.0:
            self._tokens[key] = tokens - 1.0
            return True, 0.0
        retry_after = (1.0 - tokens) / self._refill_per_second
        return False, max(0.0, retry_after)

    def reset(self) -> None:
        self._tokens.clear()
        self._updated.clear()


_rate_limiter = TokenBucketLimiter(
    settings.rate_limit_requests, settings.rate_limit_window_seconds
)


def get_rate_limiter() -> TokenBucketLimiter:
    return _rate_limiter


async def rate_limit(request: Request) -> None:
    """FastAPI dependency applying the per-client rate limit."""
    if not settings.rate_limit_enabled:
        return
    limiter = get_rate_limiter()
    limiter.configure(
        settings.rate_limit_requests, settings.rate_limit_window_seconds
    )
    allowed, retry_after = limiter.allow(client_id(request))
    if not allowed:
        raise AppError(
            429,
            "rate_limited",
            "too many requests; slow down",
            details={"retry_after_seconds": round(retry_after, 2)},
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
        )
