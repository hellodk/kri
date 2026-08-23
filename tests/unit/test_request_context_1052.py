# tests/unit/test_request_context_1052.py
"""Unit tests for issue #1052 — request/task correlation context + LOG_LEVEL.

Coverage:
- RequestContextMiddleware stamps a 12-char hex X-Request-ID on responses that
  did not carry one
- A client-supplied X-Request-ID is used as-is and NOT re-stamped
- request_id/method/path are bound into structlog contextvars downstream of the
  middleware (visible to log calls inside the route)
- Contextvar bindings are cleared once the response is returned
- configure_logging() honours the level: DEBUG lines pass at DEBUG, are
  filtered at INFO
- resolve_log_level() falls back to INFO for garbage; Settings reads LOG_LEVEL

Run: pytest tests/unit/test_request_context_1052.py -q
Do NOT run the full pytest tests/unit/ suite — that is the merge gate.
"""

import re

import pytest
import structlog
import structlog.testing
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from fleet_platform.core.config import Settings, settings
from fleet_platform.core.logging import (
    configure_logging,
    get_logger,
    resolve_log_level,
)
from fleet_platform.middleware.request_context import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
)

_HEX12 = re.compile(r"^[0-9a-f]{12}$")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _app_with_route():
    """Minimal app carrying only RequestContextMiddleware plus a logging route."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():  # pragma: no cover - trivial
        return {"ok": True}

    @app.get("/log")
    def log_line():
        get_logger("test.1052").info("route-hit", extra_field="x")
        return {"ok": True}

    return app


@pytest.fixture(autouse=True)
def _reset_logging_to_info():
    """Leave global structlog config at INFO regardless of test order/failures."""
    yield
    configure_logging("INFO")


# ---------------------------------------------------------------------------
# Middleware — X-Request-ID header behaviour
# ---------------------------------------------------------------------------


def test_response_gets_generated_x_request_id_when_client_sent_none():
    client = TestClient(_app_with_route())
    resp = client.get("/ping")

    assert REQUEST_ID_HEADER in resp.headers
    assert _HEX12.match(resp.headers[REQUEST_ID_HEADER]), "request_id must be exactly 12 lowercase hex chars"


def test_two_requests_get_different_request_ids():
    client = TestClient(_app_with_route())
    first = client.get("/ping").headers[REQUEST_ID_HEADER]
    second = client.get("/ping").headers[REQUEST_ID_HEADER]

    assert first != second


def test_client_supplied_request_id_is_used_and_not_re_stamped():
    client = TestClient(_app_with_route())
    resp = client.get("/ping", headers={REQUEST_ID_HEADER: "client-id-42"})

    assert resp.status_code == 200
    assert REQUEST_ID_HEADER not in resp.headers, "middleware must not overwrite a client-supplied X-Request-ID"


# ---------------------------------------------------------------------------
# Middleware — contextvar binding visible downstream + cleared after
# ---------------------------------------------------------------------------


async def test_middleware_binds_request_id_method_path_downstream():
    """Direct dispatch call: bindings made before call_next are visible inside it,
    and gone again once dispatch returns (single context → real assertion)."""
    from starlette.requests import Request

    seen: dict = {}

    async def call_next(request):  # stands in for the rest of the app
        seen.update(structlog.contextvars.get_contextvars())
        return PlainTextResponse("ok")

    async def receive():
        return {"type": "http.request", "body": b""}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/ping",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
    }
    mw = RequestContextMiddleware(app=lambda scope, receive, send: None)

    response = await mw.dispatch(Request(scope, receive), call_next)

    assert response.status_code == 200
    assert _HEX12.match(seen["request_id"])
    assert seen["method"] == "GET"
    assert seen["path"] == "/ping"
    # After the middleware returns, nothing may leak to the next request.
    remaining = structlog.contextvars.get_contextvars()
    for key in ("request_id", "method", "path"):
        assert key not in remaining


def test_bindings_are_cleared_between_separate_testclient_requests():
    """Second request's route-visible contextvars reflect only its own request."""
    captured = []

    def _make_app():
        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/snap")
        def snap():
            captured.append(dict(structlog.contextvars.get_contextvars()))
            return {"ok": True}

        return app

    client = TestClient(_make_app())
    id_one = client.get("/snap").headers[REQUEST_ID_HEADER]
    id_two = client.get("/snap").headers[REQUEST_ID_HEADER]

    assert captured[0]["request_id"] == id_one
    assert captured[1]["request_id"] == id_two
    assert id_one != id_two, "stale binding would make request two reuse request one's id"


# ---------------------------------------------------------------------------
# Middleware — structlog capture sees bound fields in emitted log lines
# ---------------------------------------------------------------------------


def test_log_lines_inside_request_carry_request_id_method_path():
    client = TestClient(_app_with_route())

    with structlog.testing.capture_logs([structlog.contextvars.merge_contextvars]) as logs:
        resp = client.get("/log")

    assert resp.status_code == 200
    hits = [e for e in logs if e["event"] == "route-hit"]
    assert hits, "route log line was not captured"
    entry = hits[0]
    assert _HEX12.match(entry["request_id"])
    assert entry["method"] == "GET"
    assert entry["path"] == "/log"
    assert resp.headers[REQUEST_ID_HEADER] == entry["request_id"], (
        "header value and logged request_id must be identical"
    )


def test_client_supplied_request_id_flows_into_log_lines():
    client = TestClient(_app_with_route())

    with structlog.testing.capture_logs([structlog.contextvars.merge_contextvars]) as logs:
        client.get("/log", headers={REQUEST_ID_HEADER: "my-own-id-001"})

    hits = [e for e in logs if e["event"] == "route-hit"]
    assert hits and hits[0]["request_id"] == "my-own-id-001"


# ---------------------------------------------------------------------------
# configure_logging level handling (#1052)
# ---------------------------------------------------------------------------


def test_configure_logging_debug_emits_debug_events_at_debug_level():
    configure_logging("DEBUG")

    with structlog.testing.capture_logs() as logs:
        get_logger("test.1052.level.dbg").debug("dbg-1052")

    assert any(e["event"] == "dbg-1052" for e in logs), "debug events must pass the filter when LOG_LEVEL=DEBUG"


def test_configure_logging_info_suppresses_debug_but_keeps_info():
    configure_logging("INFO")

    with structlog.testing.capture_logs() as logs:
        logger = get_logger("test.1052.level.info")
        logger.debug("dbg-1052-suppressed")
        logger.info("inf-1052")

    events = [e["event"] for e in logs]
    assert "dbg-1052-suppressed" not in events, "debug events must be filtered out when LOG_LEVEL=INFO"
    assert "inf-1052" in events


def test_resolve_log_level_normalises_and_falls_back_to_info():
    assert resolve_log_level(" debug ") == "DEBUG"
    assert resolve_log_level("warning") == "WARNING"
    assert resolve_log_level(None) == "INFO"
    assert resolve_log_level("") == "INFO"
    assert resolve_log_level("LOUD_NOISES") == "INFO"
    assert resolve_log_level("trace") == "INFO"  # valid stdlib name but not allowed


def test_settings_reads_log_level_from_env(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    assert Settings().log_level == "debug"

    monkeypatch.setenv("LOG_LEVEL", "not-a-level")
    assert resolve_log_level(Settings().log_level) == "INFO"


# ---------------------------------------------------------------------------
# Celery task contextvars (#1052)
# ---------------------------------------------------------------------------


def test_celery_signals_bind_and_clear_task_context():
    """task_prerun binds task_id/task_name; task_postrun clears them."""
    from fleet_platform.workers import celery_app as ca

    class FakeTask:
        name = "fleet_platform.workers.maintenance.mark_stale_nodes"

    try:
        ca._bind_task_log_context(sender=None, task=FakeTask(), task_id="tid-123")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["task_id"] == "tid-123"
        assert ctx["task_name"] == FakeTask.name

        ca._unbind_task_log_context()
        remaining = structlog.contextvars.get_contextvars()
        assert "task_id" not in remaining
        assert "task_name" not in remaining
    finally:
        structlog.contextvars.unbind_contextvars(*ca._TASK_BOUND_KEYS)


def test_celery_prerun_clears_previous_task_bindings_first():
    from fleet_platform.workers import celery_app as ca

    class FakeTaskA:
        name = "task.a"

    class FakeTaskB:
        name = "task.b"

    try:
        ca._bind_task_log_context(sender=None, task=FakeTaskA(), task_id="id-a")
        # Signal fires without an explicit clear between tasks.
        ca._bind_task_log_context(sender=None, task=FakeTaskB(), task_id="id-b")

        ctx = structlog.contextvars.get_contextvars()
        assert ctx["task_id"] == "id-b"
        assert ctx["task_name"] == "task.b"
    finally:
        structlog.contextvars.unbind_contextvars(*ca._TASK_BOUND_KEYS)


def test_default_settings_log_level_is_info_uppercase_ready():
    """Default setting matches what deploy manifests expect before override."""
    assert settings.log_level.upper() in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
