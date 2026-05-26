# fleet_platform/metrics.py
"""Application-level Prometheus metrics for the kri fleet platform.

All metric names are prefixed with ``kri_`` to avoid collisions with
other services scraping the same Prometheus instance.
"""
from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# HTTP request metrics (populated by PrometheusMiddleware)
# ---------------------------------------------------------------------------

http_requests_total = Counter(
    "kri_http_requests_total",
    "Total HTTP requests handled by the kri API",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "kri_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# ---------------------------------------------------------------------------
# Fleet node metrics
# ---------------------------------------------------------------------------

nodes_total = Gauge(
    "kri_nodes_total",
    "Total number of registered nodes in the fleet",
)

nodes_online = Gauge(
    "kri_nodes_online",
    "Number of nodes currently reporting as online",
)

nodes_offline = Gauge(
    "kri_nodes_offline",
    "Number of nodes currently reporting as offline",
)

# ---------------------------------------------------------------------------
# SSH session metrics
# ---------------------------------------------------------------------------

ssh_sessions_active = Gauge(
    "kri_ssh_sessions_active",
    "Number of SSH sessions currently active",
)

ssh_sessions_total = Counter(
    "kri_ssh_sessions_total",
    "Total number of SSH sessions created since last restart",
)

# ---------------------------------------------------------------------------
# Celery task metrics
# ---------------------------------------------------------------------------

celery_tasks_total = Counter(
    "kri_celery_tasks_total",
    "Total Celery tasks dispatched",
    ["task_name", "status"],
)
