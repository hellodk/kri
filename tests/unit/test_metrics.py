# tests/unit/test_metrics.py
"""Unit tests for the Prometheus metrics module and /metrics endpoint."""

import contextlib

_METRICS_TOKEN = "test-metrics-token"


@contextlib.contextmanager
def _metrics_auth():
    """Authorize /metrics for the duration of the block (#763).

    The endpoint now requires a bearer credential — either the static
    METRICS_TOKEN or a valid JWT. Patch a known token and hand back the header.
    """
    from unittest.mock import patch

    from fleet_platform.core.config import settings

    with patch.object(settings, "metrics_token", _METRICS_TOKEN):
        yield {"Authorization": f"Bearer {_METRICS_TOKEN}"}


def test_metrics_module_exports_node_gauges():
    from fleet_platform.metrics import nodes_offline, nodes_online, nodes_total

    assert nodes_total._name == "kri_nodes_total"
    assert nodes_online._name == "kri_nodes_online"
    assert nodes_offline._name == "kri_nodes_offline"


def test_metrics_module_exports_ssh_metrics():
    from fleet_platform.metrics import ssh_sessions_active, ssh_sessions_total

    # prometheus_client strips _total suffix from Counter._name internally
    assert ssh_sessions_active._name == "kri_ssh_sessions_active"
    assert "kri_ssh_sessions" in ssh_sessions_total._name


def test_metrics_module_exports_http_metrics():
    from fleet_platform.metrics import http_request_duration_seconds, http_requests_total

    assert "kri_http_requests" in http_requests_total._name
    assert http_request_duration_seconds._name == "kri_http_request_duration_seconds"


def test_metrics_module_exports_celery_metrics():
    from fleet_platform.metrics import celery_tasks_total

    assert "kri_celery_tasks" in celery_tasks_total._name


def test_metrics_endpoint_returns_200():
    from fastapi.testclient import TestClient

    from fleet_platform.api.main import app

    client = TestClient(app)
    with _metrics_auth() as headers:
        response = client.get("/metrics", headers=headers)
    assert response.status_code == 200


def test_metrics_endpoint_content_type_is_text_plain():
    from fastapi.testclient import TestClient

    from fleet_platform.api.main import app

    client = TestClient(app)
    with _metrics_auth() as headers:
        response = client.get("/metrics", headers=headers)
    assert "text/plain" in response.headers["content-type"]


def test_metrics_endpoint_includes_kri_counter():
    from fastapi.testclient import TestClient

    from fleet_platform.api.main import app

    client = TestClient(app)
    # Make a real request so the counter is seeded
    client.get("/health")
    with _metrics_auth() as headers:
        response = client.get("/metrics", headers=headers)
    assert "kri_http_requests_total" in response.text


def test_metrics_endpoint_includes_node_gauges():
    from fastapi.testclient import TestClient

    from fleet_platform.api.main import app

    client = TestClient(app)
    with _metrics_auth() as headers:
        response = client.get("/metrics", headers=headers)
    assert "kri_nodes_total" in response.text
    assert "kri_nodes_online" in response.text
    assert "kri_nodes_offline" in response.text
