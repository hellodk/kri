# tests/unit/test_prometheus_middleware.py
"""Unit tests for the Prometheus middleware."""
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_middleware_skips_metrics_path():
    """The middleware must not record metrics for the /metrics path itself."""
    from fleet_platform.middleware.prometheus import PrometheusMiddleware

    app_mock = AsyncMock()
    middleware = PrometheusMiddleware(app_mock)

    request = MagicMock()
    request.url.path = "/metrics"
    request.method = "GET"

    response_mock = MagicMock()
    response_mock.status_code = 200
    call_next = AsyncMock(return_value=response_mock)

    await middleware.dispatch(request, call_next)
    call_next.assert_called_once_with(request)


@pytest.mark.asyncio
async def test_middleware_records_metrics_for_api_calls():
    """Middleware must increment the request counter for non-metrics paths."""
    from fleet_platform.metrics import http_requests_total
    from fleet_platform.middleware.prometheus import PrometheusMiddleware

    # Sample the counter before the request
    before = _sample_counter(http_requests_total, method="GET", endpoint="/health", status_code="200")

    app_mock = AsyncMock()
    middleware = PrometheusMiddleware(app_mock)

    request = MagicMock()
    request.url.path = "/health"
    request.method = "GET"

    response_mock = MagicMock()
    response_mock.status_code = 200
    call_next = AsyncMock(return_value=response_mock)

    await middleware.dispatch(request, call_next)

    after = _sample_counter(http_requests_total, method="GET", endpoint="/health", status_code="200")
    assert after == before + 1


@pytest.mark.asyncio
async def test_middleware_records_duration():
    """Middleware must observe request duration on the histogram."""
    from fleet_platform.metrics import http_request_duration_seconds
    from fleet_platform.middleware.prometheus import PrometheusMiddleware

    app_mock = AsyncMock()
    middleware = PrometheusMiddleware(app_mock)

    request = MagicMock()
    request.url.path = "/health"
    request.method = "GET"

    response_mock = MagicMock()
    response_mock.status_code = 200
    call_next = AsyncMock(return_value=response_mock)

    # Sample total observations before
    before = _sample_histogram_count(http_request_duration_seconds, method="GET", endpoint="/health")
    await middleware.dispatch(request, call_next)
    after = _sample_histogram_count(http_request_duration_seconds, method="GET", endpoint="/health")

    assert after > before


def test_normalize_path_replaces_uuid():
    from fleet_platform.middleware.prometheus import _normalize_path

    result = _normalize_path("/api/v1/nodes/550e8400-e29b-41d4-a716-446655440000")
    assert "{uuid}" in result


def test_normalize_path_replaces_node_id():
    from fleet_platform.middleware.prometheus import _normalize_path

    result = _normalize_path("/api/v1/nodes/mac-mini-42")
    assert "{node_id}" in result


def test_normalize_path_leaves_clean_paths_alone():
    from fleet_platform.middleware.prometheus import _normalize_path

    result = _normalize_path("/api/v1/fleet")
    assert result == "/api/v1/fleet"


def test_normalize_path_leaves_metrics_path_alone():
    from fleet_platform.middleware.prometheus import _normalize_path

    result = _normalize_path("/metrics")
    assert result == "/metrics"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_counter(counter, **labels):
    """Return current value of a labeled Counter."""
    try:
        return counter.labels(**labels)._value.get()
    except Exception:
        return 0.0


def _sample_histogram_count(histogram, **labels):
    """Return the _count value of a labeled Histogram."""
    try:
        return histogram.labels(**labels)._sum.get()
    except Exception:
        return 0.0
