"""Tests for node resource metrics storage and filtering (#287 #288)."""


def test_safe_float_extracts_nested_key():
    from fleet_platform.api.routes.ingest import _safe_float

    assert _safe_float({"virtual_memory": {"percent": 72.5}}, "virtual_memory.percent") == 72.5


def test_safe_float_returns_none_for_missing():
    from fleet_platform.api.routes.ingest import _safe_float

    assert _safe_float({}, "cpu_percent", "ps.cpu_percent") is None


def test_safe_float_returns_first_match():
    from fleet_platform.api.routes.ingest import _safe_float

    assert _safe_float({"cpu_percent": 55.0, "ps.cpu_percent": 60.0}, "cpu_percent", "ps.cpu_percent") == 55.0


def test_safe_float_skips_non_numeric():
    from fleet_platform.api.routes.ingest import _safe_float

    assert _safe_float({"cpu_percent": "bad"}, "cpu_percent") is None


def test_safe_float_handles_integer_value():
    from fleet_platform.api.routes.ingest import _safe_float

    assert _safe_float({"gpu_percent": 42}, "gpu_percent") == 42.0


def test_extract_node_updates_includes_resource_metrics():
    from fleet_platform.api.routes.ingest import _extract_node_updates

    grains = {"cpu_percent": 45.2, "mem_percent": 67.8, "id": "mm1", "fqdn": "mm1.local"}
    result = _extract_node_updates(grains)
    assert result["cpu_usage_pct"] == 45.2
    assert result["mem_usage_pct"] == 67.8


def test_extract_node_updates_resource_metrics_none_when_absent():
    from fleet_platform.api.routes.ingest import _extract_node_updates

    grains = {"id": "mm2", "fqdn": "mm2.local"}
    result = _extract_node_updates(grains)
    assert result["cpu_usage_pct"] is None
    assert result["mem_usage_pct"] is None
    assert result["disk_io_read_kbs"] is None
    assert result["disk_io_write_kbs"] is None
    assert result["gpu_usage_pct"] is None


def test_node_model_has_resource_metric_columns():
    from sqlalchemy import inspect as sa_inspect

    from fleet_platform.models.node import Node

    cols = {c.key for c in sa_inspect(Node).columns}
    assert "cpu_usage_pct" in cols
    assert "mem_usage_pct" in cols
    assert "disk_io_read_kbs" in cols
    assert "disk_io_write_kbs" in cols
    assert "gpu_usage_pct" in cols
