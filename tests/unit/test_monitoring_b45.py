"""Behavioral tests for #45: monitoring stats page.

Backend checks now import the real router/app and the real response schemas and
assert on the registered route + declared model fields, instead of scraping
``monitoring.py`` / ``main.py`` for substrings. Frontend asset checks stay as
file-existence / source-contract tests (frontend-owned).
"""

from pathlib import Path

from fleet_platform.api.routes.monitoring import monitoring_summary, router
from fleet_platform.schemas.monitoring import MonitoringSummarySchema, NodeCountsSchema


def _route_for(endpoint) -> object:
    for r in router.routes:
        if getattr(r, "endpoint", None) is endpoint:
            return r
    raise AssertionError(f"No route registered for {endpoint!r}")


# ---------------------------------------------------------------------------
# Route contract (real router + app)
# ---------------------------------------------------------------------------


def test_monitoring_router_prefixed():
    assert router.prefix == "/api/v1/monitoring"


def test_monitoring_summary_endpoint_defined():
    route = _route_for(monitoring_summary)
    assert route.path == "/api/v1/monitoring/summary"


def test_monitoring_registered_in_app():
    """The monitoring summary route must be mounted on the real FastAPI app."""
    from fleet_platform.api.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/monitoring/summary" in paths


# ---------------------------------------------------------------------------
# Response schema contract (real Pydantic models)
# ---------------------------------------------------------------------------


def test_monitoring_returns_node_counts():
    assert "node_counts" in MonitoringSummarySchema.model_fields
    node_count_fields = set(NodeCountsSchema.model_fields.keys())
    assert "online" in node_count_fields
    assert "offline" in node_count_fields


def test_monitoring_returns_queue_depths():
    assert "celery_queues" in MonitoringSummarySchema.model_fields


def test_node_counts_schema_roundtrips():
    counts = NodeCountsSchema(online=3, stale=1, offline=2, unknown=0, total=6)
    assert counts.online == 3
    assert counts.total == 6


# ---------------------------------------------------------------------------
# Frontend assets — file-existence / source-contract checks (frontend-owned).
# ---------------------------------------------------------------------------


def test_monitoring_ts_api_exists():
    assert Path("frontend/src/api/monitoring.ts").exists()


def test_monitoring_page_exists():
    assert Path("frontend/src/pages/MonitoringPage.tsx").exists()


def test_monitoring_page_uses_usequery():
    src = Path("frontend/src/pages/MonitoringPage.tsx").read_text()
    assert "useQuery" in src


def test_monitoring_reachable_from_sidebar():
    src = Path("frontend/src/components/Layout/Sidebar.tsx").read_text()
    assert "/overview" in src.lower() or "overview" in src.lower(), (
        "Sidebar must include /overview which hosts the Monitoring tab"
    )
