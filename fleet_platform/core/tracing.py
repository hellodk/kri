"""OpenTelemetry tracing setup.

Wires a real OTLP-gRPC tracer provider so the `trace_id` injected into
structlog records maps to a span visible in Tempo / Jaeger / any OTLP
backend, replacing the random UUID4 fallback in ``core/logging.py``.

The setup is gated on ``OTEL_EXPORTER_OTLP_ENDPOINT`` being set: if the env
var is missing (e.g. in dev or in tests) the tracer becomes a no-op rather
than crashing on a missing collector. Service identity is read from the
``OTEL_SERVICE_NAME`` env var with a sensible default.

Usage::

    from fleet_platform.core.tracing import configure_tracing

    # Once at startup, before instrumentation hooks fire.
    configure_tracing()
    instrument_fastapi(app)
    instrument_sqlalchemy(engine)
    instrument_httpx()
    instrument_redis()

Each ``instrument_*`` helper is idempotent and short-circuits if the SDK is
unavailable so workers running without OTEL deps installed (e.g. older
container builds) don't crash on import.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_log = logging.getLogger(__name__)

_configured = False


def configure_tracing(service_name: str | None = None) -> None:
    """Initialise the global tracer provider, idempotently.

    Reads configuration from standard OTEL env vars:
        OTEL_EXPORTER_OTLP_ENDPOINT  e.g. http://tempo.observability.svc:4317
        OTEL_EXPORTER_OTLP_HEADERS   e.g. authorization=Bearer xxx
        OTEL_SERVICE_NAME            defaults to ``service_name`` arg or "kri"
        OTEL_RESOURCE_ATTRIBUTES     extra k=v,k2=v2 pairs

    A missing endpoint disables tracing rather than crashing — this lets the
    same code path run in dev (no collector) and in production.
    """
    global _configured
    if _configured:
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        _log.info("otel: OTEL_EXPORTER_OTLP_ENDPOINT unset, tracing disabled")
        _configured = True
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover — packaging gate
        _log.warning("otel: SDK not importable, tracing disabled: %s", exc)
        _configured = True
        return

    resolved_service: str = service_name or os.getenv("OTEL_SERVICE_NAME") or "kri"
    resource = Resource.create({SERVICE_NAME: resolved_service})

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    _log.info("otel: tracer initialised service=%s endpoint=%s", resolved_service, endpoint)
    _configured = True


def instrument_fastapi(app: Any) -> None:
    """Wrap a FastAPI app so every HTTP handler becomes a root span."""
    if not _configured:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:  # pragma: no cover
        return
    FastAPIInstrumentor.instrument_app(app)


def instrument_sqlalchemy(engine: Any | None = None) -> None:
    """Wrap SQLAlchemy so every query is a span. ``engine`` may be None to
    instrument all engines (the recommended default)."""
    if not _configured:
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    except ImportError:  # pragma: no cover
        return
    instrumentor = SQLAlchemyInstrumentor()
    if engine is not None:
        # When a specific engine is provided, attach to it only.
        instrumentor.instrument(engine=engine)
    else:
        # Otherwise instrument the global SQLAlchemy event hooks so any engine
        # created later picks up tracing automatically.
        instrumentor.instrument()


def instrument_httpx() -> None:
    """Wrap httpx so outbound API calls (LLM, Salt API) propagate trace context."""
    if not _configured:
        return
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except ImportError:  # pragma: no cover
        return
    HTTPXClientInstrumentor().instrument()


def instrument_redis() -> None:
    """Wrap redis-py so Celery's broker/backend traffic appears as spans."""
    if not _configured:
        return
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
    except ImportError:  # pragma: no cover
        return
    RedisInstrumentor().instrument()


def instrument_celery() -> None:
    """Wrap Celery worker tasks so each task becomes a span. Call from inside
    the worker process (worker_process_init signal) — instrumenting from the
    API process is harmless but does not benefit it."""
    if not _configured:
        return
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
    except ImportError:  # pragma: no cover
        return
    CeleryInstrumentor().instrument()


@contextmanager
def agent_span(
    name: str,
    *,
    actor: str | None = None,
    session_id: object | None = None,
    tool_name: str | None = None,
    **attrs: Any,
) -> Iterator[Any]:
    """Span for an agent operation (loop step / tool dispatch) (#710).

    Always carries the operator email (``actor``) so every span answers
    "who fired this?" — the confused-deputy guarantee (#714). Degrades to a
    no-op if the OTEL SDK is unavailable or no provider is configured, so the
    agent loop runs identically in dev, tests and production.
    """
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover — packaging gate
        yield None
        return

    attributes: dict[str, Any] = {}
    if actor:
        attributes["kri.actor"] = actor
    if session_id is not None:
        attributes["kri.agent.session_id"] = str(session_id)
    if tool_name:
        attributes["kri.agent.tool"] = tool_name
    for key, value in attrs.items():
        if value is not None:
            attributes[f"kri.agent.{key}"] = value

    tracer = trace.get_tracer("kri.agent")
    with tracer.start_as_current_span(name, attributes=attributes) as span:
        yield span


def current_trace_id_hex() -> str | None:
    """Return the hex trace_id of the active span, or None if no span is
    active or the SDK is not configured. Used by core/logging.py to bind the
    real trace_id into structlog records instead of a random UUID4."""
    if not _configured:
        return None
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover
        return None
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    # Format as 32-char lowercase hex (the W3C trace-context standard).
    return f"{ctx.trace_id:032x}"
