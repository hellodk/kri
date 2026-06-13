"""Unit tests for O1: real OTEL tracing wiring.

These tests verify the no-op behaviour when OTEL_EXPORTER_OTLP_ENDPOINT is
unset (dev / tests / users without an OTEL backend) and that the trace_id
helper degrades cleanly. The full SDK behaviour is covered by integration
tests against a tempo collector (out of unit-test scope).
"""

import importlib

import fleet_platform.core.tracing as tracing


def _reset_tracing_module():
    """Reload the tracing module so each test gets a fresh ``_configured`` flag."""
    importlib.reload(tracing)


def test_configure_tracing_is_noop_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    _reset_tracing_module()
    tracing.configure_tracing()
    # current_trace_id_hex must return None when no provider is wired,
    # so logging.py falls back to a UUID4 instead of crashing.
    assert tracing.current_trace_id_hex() is None


def test_configure_tracing_is_idempotent(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    _reset_tracing_module()
    tracing.configure_tracing()
    # Second call must not raise even though ``_configured`` is already True.
    tracing.configure_tracing()


def test_instrumentation_helpers_are_safe_when_unconfigured(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    _reset_tracing_module()
    # All instrument_* helpers must short-circuit when configure_tracing()
    # decided tracing was disabled. Calling them on a fresh module (without
    # configure_tracing first) must also be safe.
    tracing.instrument_fastapi(object())
    tracing.instrument_sqlalchemy()
    tracing.instrument_httpx()
    tracing.instrument_redis()
    tracing.instrument_celery()


def test_logging_falls_back_to_uuid_when_no_span(monkeypatch):
    """logging._add_trace_id must produce a non-empty trace_id even with no SDK."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    _reset_tracing_module()

    from fleet_platform.core.logging import _add_trace_id

    record: dict = {}
    _add_trace_id(None, "info", record)
    assert "trace_id" in record
    # Either a 32-char hex OTEL trace_id or a UUID4 string. Both are non-empty.
    assert record["trace_id"]
    assert len(record["trace_id"]) >= 16


def test_logging_preserves_explicit_trace_id():
    """A trace_id already on the record must NOT be overwritten."""
    from fleet_platform.core.logging import _add_trace_id

    record = {"trace_id": "explicit-trace-id"}
    out = _add_trace_id(None, "info", record)
    assert out["trace_id"] == "explicit-trace-id"
