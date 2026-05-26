# tests/unit/test_metrics.py
"""Unit tests for the Prometheus metrics module and /metrics endpoint."""
import pytest


def test_metrics_module_exports_node_gauges():
    from fleet_platform.metrics import nodes_total, nodes_online, nodes_offline

    assert nodes_total._name == "kri_nodes_total"
    assert nodes_online._name == "kri_nodes_online"
    assert nodes_offline._name == "kri_nodes_offline"


def test_metrics_module_exports_ssh_metrics():
    from fleet_platform.metrics import ssh_sessions_active, ssh_sessions_total

    # prometheus_client strips _total suffix from Counter._name internally
    assert ssh_sessions_active._name == "kri_ssh_sessions_active"
    assert "kri_ssh_sessions" in ssh_sessions_total._name


def test_metrics_module_exports_http_metrics():
    from fleet_platform.metrics import http_requests_total, http_request_duration_seconds

    assert "kri_http_requests" in http_requests_total._name
    assert http_request_duration_seconds._name == "kri_http_request_duration_seconds"


def test_metrics_module_exports_celery_metrics():
    from fleet_platform.metrics import celery_tasks_total

    assert "kri_celery_tasks" in celery_tasks_total._name


def test_metrics_endpoint_returns_200():
    from fastapi.testclient import TestClient
    from fleet_platform.api.main import app

    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_endpoint_content_type_is_text_plain():
    from fastapi.testclient import TestClient
    from fleet_platform.api.main import app

    client = TestClient(app)
    response = client.get("/metrics")
    assert "text/plain" in response.headers["content-type"]


def test_metrics_endpoint_includes_kri_counter():
    from fastapi.testclient import TestClient
    from fleet_platform.api.main import app

    client = TestClient(app)
    # Make a real request so the counter is seeded
    client.get("/health")
    response = client.get("/metrics")
    assert "kri_http_requests_total" in response.text


def test_metrics_endpoint_includes_node_gauges():
    from fastapi.testclient import TestClient
    from fleet_platform.api.main import app

    client = TestClient(app)
    response = client.get("/metrics")
    assert "kri_nodes_total" in response.text
    assert "kri_nodes_online" in response.text
    assert "kri_nodes_offline" in response.text
