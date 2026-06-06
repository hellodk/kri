# fleet_platform/middleware/prometheus.py
"""Starlette middleware that records Prometheus HTTP metrics for every request.

The /metrics endpoint itself is excluded to avoid self-referential noise in
the data.  Path labels are normalised to prevent high cardinality from node
IDs and UUIDs becoming separate time-series.
"""

import re
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from fleet_platform.metrics import http_request_duration_seconds, http_requests_total

# Pre-compiled patterns for path normalisation — order matters:
# UUID pattern must run before the generic node-id pattern so that
# /nodes/<uuid> is collapsed to /nodes/{uuid} not /nodes/{node_id}/{uuid}.
_UUID_RE = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Exclude placeholder tokens ({uuid}, {node_id}) already substituted by _UUID_RE
_NODE_ID_RE = re.compile(r"/nodes/(?!\{)[^/]+")


def _normalize_path(path: str) -> str:
    """Replace dynamic segments in *path* with stable placeholder tokens.

    Examples::

        /api/v1/nodes/mac-mini-42          → /api/v1/nodes/{node_id}
        /api/v1/nodes/550e8400-…-440000    → /api/v1/nodes/{uuid}
        /api/v1/fleet                      → /api/v1/fleet  (unchanged)
    """
    path = _UUID_RE.sub("/{uuid}", path)
    path = _NODE_ID_RE.sub("/nodes/{node_id}", path)
    return path


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record ``kri_http_requests_total`` and ``kri_http_request_duration_seconds``
    for every inbound HTTP request, skipping the /metrics scrape endpoint itself.
    """

    async def dispatch(self, request: Request, call_next):
        # Never instrument the scrape endpoint — that creates a feedback loop.
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        path = _normalize_path(request.url.path)

        http_requests_total.labels(
            method=request.method,
            endpoint=path,
            status_code=str(response.status_code),
        ).inc()

        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=path,
        ).observe(duration)

        return response
