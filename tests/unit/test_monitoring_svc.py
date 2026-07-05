"""Tests for monitoring_svc — unit tests with mocked DB and Redis."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_parse_http_request_total_empty():
    from fleet_platform.services.monitoring_svc import parse_http_request_total

    assert parse_http_request_total("") == []


def test_parse_http_request_total_basic():
    from fleet_platform.services.monitoring_svc import parse_http_request_total

    text = """# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{handler="/api/v1/fleet",method="GET",status_code="200"} 42
http_requests_total{handler="/api/v1/nodes",method="GET",status_code="200"} 17
http_requests_total{handler="/api/v1/nodes",method="GET",status_code="404"} 3
"""
    results = parse_http_request_total(text)
    assert len(results) == 3
    assert results[0]["handler"] == "/api/v1/fleet"
    assert results[0]["count"] == 42
    assert results[1]["status_code"] == "200"


def test_parse_http_request_total_malformed():
    from fleet_platform.services.monitoring_svc import parse_http_request_total

    text = "# just a comment\nsome_other_metric 123\n"
    assert parse_http_request_total(text) == []


@pytest.mark.asyncio
async def test_get_node_counts_all_online():
    from fleet_platform.services.monitoring_svc import get_node_counts

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [("online", 5), ("offline", 2)]
    mock_db.execute = AsyncMock(return_value=mock_result)

    counts = await get_node_counts(mock_db)
    assert counts["online"] == 5
    assert counts["offline"] == 2
    assert counts["stale"] == 0
    assert counts["total"] == 7


@pytest.mark.asyncio
async def test_get_node_counts_empty():
    from fleet_platform.services.monitoring_svc import get_node_counts

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    counts = await get_node_counts(mock_db)
    assert counts["total"] == 0
    assert counts["online"] == 0


@pytest.mark.asyncio
async def test_get_celery_queue_stats_redis_unavailable():
    from fleet_platform.services.monitoring_svc import get_celery_queue_stats

    with patch("fleet_platform.services.monitoring_svc.get_redis", side_effect=Exception("connection refused")):
        stats = await get_celery_queue_stats()
    assert {"default", "maintenance", "drift", "sbom", "active"}.issubset(stats.keys())
    assert stats["default"] == 0
    assert stats["maintenance"] == 0
    assert stats["drift"] == 0
    assert stats["sbom"] == 0


@pytest.mark.asyncio
async def test_get_celery_queue_stats_returns_counts():
    from fleet_platform.services.monitoring_svc import get_celery_queue_stats

    mock_redis = AsyncMock()
    mock_redis.llen = AsyncMock(side_effect=lambda q: {"default": 3, "maintenance": 0, "drift": 1, "sbom": 0}.get(q, 0))

    mock_inspector = MagicMock()
    mock_inspector.active.return_value = {"worker1": [{"id": "task1"}, {"id": "task2"}]}
    mock_celery = MagicMock()
    mock_celery.control.inspect.return_value = mock_inspector

    with patch("fleet_platform.services.monitoring_svc.get_redis", return_value=mock_redis):
        with patch("fleet_platform.workers.celery_app.celery_app", mock_celery):
            stats = await get_celery_queue_stats()
    assert stats["default"] == 3
    assert stats["drift"] == 1
    assert "active" in stats


@pytest.mark.asyncio
async def test_get_alert_events_24h_empty():
    from fleet_platform.services.monitoring_svc import get_alert_events_24h

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    events = await get_alert_events_24h(mock_db)
    assert events == []


@pytest.mark.asyncio
async def test_get_monitoring_summary_structure():
    from fleet_platform.services.monitoring_svc import get_monitoring_summary

    mock_db = AsyncMock()

    node_result = MagicMock()
    node_result.all.return_value = [("online", 3)]
    alert_result = MagicMock()
    alert_result.all.return_value = []
    health_result = MagicMock()
    health_result.all.return_value = []
    mock_db.execute = AsyncMock(side_effect=[node_result, alert_result, health_result])

    with patch("fleet_platform.services.monitoring_svc.get_redis", side_effect=Exception("no redis")):
        summary = await get_monitoring_summary(mock_db, "")

    assert "node_counts" in summary
    assert "celery_queues" in summary
    assert "alert_events_24h" in summary
    assert "alert_count_24h" in summary
    assert "generated_at" in summary
    assert "active" in summary["celery_queues"]


@pytest.mark.asyncio
async def test_get_node_counts_mixed_with_unknown_statuses():
    from fleet_platform.services.monitoring_svc import get_node_counts

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [("online", 3), ("unknown", 2), ("degraded", 1)]
    mock_db.execute = AsyncMock(return_value=mock_result)
    counts = await get_node_counts(mock_db)
    # "degraded" falls into unknown bucket, so unknown = 2 + 1 = 3
    assert counts["unknown"] == 3
    assert counts["online"] == 3
    assert counts["total"] == 6


def test_monitoring_summary_endpoint_registered():
    """Verify /api/v1/monitoring/summary route is registered in the FastAPI app."""
    from fleet_platform.api.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/monitoring/summary" in paths


def test_monitoring_summary_schema_fields():
    """Verify MonitoringSummarySchema has all expected fields."""
    from fleet_platform.schemas.monitoring import MonitoringSummarySchema

    fields = set(MonitoringSummarySchema.model_fields.keys())
    assert "node_counts" in fields
    assert "celery_queues" in fields
    assert "alert_events_24h" in fields
    assert "alert_count_24h" in fields
    assert "generated_at" in fields


def test_celery_queues_schema_has_active():
    """Verify CeleryQueuesSchema includes the active field."""
    from fleet_platform.schemas.monitoring import CeleryQueuesSchema

    fields = set(CeleryQueuesSchema.model_fields.keys())
    assert "active" in fields


def test_get_monitoring_summary_returns_dict():
    """get_monitoring_summary handles missing Redis gracefully."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.services.monitoring_svc import get_monitoring_summary

    async def _run():
        db = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one.return_value = 0
        mock_res.scalars.return_value.all.return_value = []
        mock_res.all.return_value = []
        db.execute = AsyncMock(return_value=mock_res)
        with patch("fleet_platform.services.monitoring_svc.get_celery_queue_stats", return_value={}):
            return await get_monitoring_summary(db)

    result = asyncio.run(_run())
    assert isinstance(result, dict)
