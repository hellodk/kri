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

# ---------------------------------------------------------------------------
# SSH reachability metrics (issue #356)
# ---------------------------------------------------------------------------

node_ssh_reachable = Gauge(
    "kri_node_ssh_reachable",
    "1 if the node's SSH port is reachable (probed every 15 min by the connectivity worker), 0 otherwise",
    ["minion_id"],
)

# ---------------------------------------------------------------------------
# Celery beat dead-man heartbeat gauge (issue #576)
# ---------------------------------------------------------------------------

beat_last_run_timestamp_seconds = Gauge(
    "kri_beat_last_run_timestamp_seconds",
    "Unix timestamp (seconds) of the last successful Celery beat mark_stale_nodes run. "
    "0 when the kri:maintenance:last_run Redis key is absent (beat is silent / dead). "
    "Alert: time() - kri_beat_last_run_timestamp_seconds > 600",
)

# ---------------------------------------------------------------------------
# Node action control-plane metrics (issue #661 / audit #639)
# ---------------------------------------------------------------------------

node_action_total = Counter(
    "kri_node_action_total",
    "Node control-plane actions by type and lifecycle status",
    ["action_type", "status"],
)

pending_action_queue_depth = Gauge(
    "kri_pending_action_queue_depth",
    "Pending node actions awaiting approval or execution (status in pending|executing)",
)

# ---------------------------------------------------------------------------
# Process-stats ingest metrics (issue #661 / audit #639)
# ---------------------------------------------------------------------------

process_stats_rows_ingested_total = Counter(
    "kri_process_stats_rows_ingested_total",
    "Per-process stat rows persisted from the ingest endpoint",
)

process_stats_rows_dropped_total = Counter(
    "kri_process_stats_rows_dropped_total",
    "Per-process stat rows dropped by the per-payload cap",
)

# ---------------------------------------------------------------------------
# Salt dispatch metrics (issue #661 / audit #639)
# ---------------------------------------------------------------------------

salt_dispatch_total = Counter(
    "kri_salt_dispatch_total",
    "salt-api dispatches via run_salt_cmd by function and outcome",
    ["function", "outcome"],
)

# ---------------------------------------------------------------------------
# Embedding index staleness (issue #1027)
# ---------------------------------------------------------------------------

embedding_index_staleness_seconds = Gauge(
    "kri_embedding_index_staleness_seconds",
    "Seconds since the oldest embedding was last refreshed. 0 when no embeddings exist. Alert: > 3600",
)
