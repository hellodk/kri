"""Tests for #45: monitoring stats page."""
from pathlib import Path


def test_monitoring_route_file_exists():
    assert Path("fleet_platform/api/routes/monitoring.py").exists()


def test_monitoring_summary_endpoint_defined():
    src = Path("fleet_platform/api/routes/monitoring.py").read_text()
    assert "monitoring_summary" in src
    assert "/api/v1/monitoring" in src


def test_monitoring_returns_node_counts():
    src = Path("fleet_platform/schemas/monitoring.py").read_text()
    assert "node_counts" in src
    assert "online" in src
    assert "offline" in src


def test_monitoring_returns_queue_depths():
    src = Path("fleet_platform/schemas/monitoring.py").read_text()
    assert "celery_queues" in src


def test_monitoring_registered_in_main():
    src = Path("fleet_platform/api/main.py").read_text()
    assert "monitoring_router" in src or "monitoring" in src


def test_monitoring_ts_api_exists():
    assert Path("frontend/src/api/monitoring.ts").exists()


def test_monitoring_page_exists():
    assert Path("frontend/src/pages/MonitoringPage.tsx").exists()


def test_monitoring_page_uses_usequery():
    src = Path("frontend/src/pages/MonitoringPage.tsx").read_text()
    assert "useQuery" in src


def test_monitoring_reachable_from_sidebar():
    # Monitoring is a tab inside the Overview hub page — the sidebar links to /overview
    src = Path("frontend/src/components/Layout/Sidebar.tsx").read_text()
    assert "/overview" in src.lower() or "overview" in src.lower(), (
        "Sidebar must include /overview which hosts the Monitoring tab"
    )
