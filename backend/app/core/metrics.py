from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)

registry = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "agents_http_requests_total",
    "Total HTTP requests.",
    ["method", "route", "status"],
    registry=registry,
)
HTTP_DURATION = Histogram(
    "agents_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "route"],
    registry=registry,
)
RUNS_TOTAL = Counter(
    "agents_runs_total",
    "Runs that reached a terminal status.",
    ["agent", "status"],
    registry=registry,
)
RUNS_ACTIVE = Gauge(
    "agents_runs_active",
    "Runs currently executing.",
    registry=registry,
)
SEARCH_TOTAL = Counter(
    "agents_search_total",
    "Web searches by outcome.",
    ["outcome"],
    registry=registry,
)


def observe_http(method: str, route: str, status: int, duration: float) -> None:
    HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, route=route).observe(duration)


def observe_run_status(agent: str, status: str) -> None:
    RUNS_TOTAL.labels(agent=agent, status=status).inc()


def run_started() -> None:
    RUNS_ACTIVE.inc()


def run_finished() -> None:
    RUNS_ACTIVE.dec()


def observe_search(outcome: str) -> None:
    SEARCH_TOTAL.labels(outcome=outcome).inc()
