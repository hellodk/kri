import logging
import uuid

import structlog


def _add_service_field(logger, method, event_dict):  # noqa: ARG001
    """Inject a static ``service`` key into every log record.

    The value is always ``"kri"`` — added here so downstream log-shipping
    pipelines (Loki/Promtail, OTEL) can filter by service without touching
    every call site.  Issue #576.
    """
    event_dict.setdefault("service", "kri")
    return event_dict


def _add_trace_id(logger, method, event_dict):  # noqa: ARG001
    """Inject a ``trace_id`` into every log record.

    In order of preference:
    1. ``trace_id`` already bound to the structlog context (set explicitly by
       a caller via ``structlog.contextvars.bind_contextvars``).
    2. The hex trace_id of the active OpenTelemetry span (set by
       ``configure_tracing`` + the FastAPI / Celery instrumentors). This is
       the same value that the OTLP exporter ships to Tempo / Jaeger, so
       grepping logs by trace_id and clicking through to a trace are
       guaranteed to find the same record.
    3. A fresh UUID4 so the field is always present even when no OTEL
       collector is configured (dev / tests).

    Issue #576: trace_id must appear in every structured log line so that
    log-to-trace linking works from day one.
    """
    if "trace_id" in event_dict:
        return event_dict
    # Local import keeps logging.py importable when OTEL deps are absent.
    from fleet_platform.core.tracing import current_trace_id_hex

    real = current_trace_id_hex()
    event_dict["trace_id"] = real if real else str(uuid.uuid4())
    return event_dict


_VALID_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})


def resolve_log_level(raw: str | None) -> str:
    """Normalise a requested log level name; unknown values fall back to INFO.

    ``logging.getLevelName()`` returns a nonsense string ("Level BOGUS") for
    unknown names instead of raising, so an unvalidated LOG_LEVEL env var would
    silently break both the structlog filter and stdlib basicConfig (#1052).
    """
    level = (raw or "").strip().upper()
    return level if level in _VALID_LOG_LEVELS else "INFO"


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            _add_service_field,
            _add_trace_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=logging.getLevelName(level),
    )


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
