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
    1. ``trace_id`` already bound to the structlog context (set by OTEL
       instrumentation or middleware via ``structlog.contextvars.bind_contextvars``).
    2. A fresh UUID4 so the field is always present and log records can be
       correlated within a single request even without a full OTEL pipeline.

    Issue #576: trace_id must appear in every structured log line so that
    log-to-trace linking works from day one.
    """
    if "trace_id" not in event_dict:
        # Fall back to a fresh UUID so the field is never absent.
        event_dict["trace_id"] = str(uuid.uuid4())
    return event_dict


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
