# tests/unit/test_node_health_snapshot.py
from sqlalchemy import inspect as sa_inspect


def test_node_health_snapshot_tablename():
    from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
    assert NodeHealthSnapshot.__tablename__ == "node_health_snapshots"


def test_node_health_snapshot_has_required_columns():
    from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
    mapper = sa_inspect(NodeHealthSnapshot)
    col_names = {c.key for c in mapper.columns}
    expected = {
        "id", "node_id", "minion_id", "collected_at",
        "disk_root_used_gb", "disk_root_total_gb", "disk_root_pct", "disk_root_inodes_pct",
        "mem_total_gb", "mem_available_gb", "mem_used_pct",
        "cpu_load_1m", "cpu_load_5m", "cpu_load_15m",
        "uptime_seconds",
        "gpu_name", "gpu_vram_mb",
        "cpu_power_mw", "gpu_power_mw", "thermal_pressure",
        "error",
    }
    assert expected.issubset(col_names), f"Missing: {expected - col_names}"


def test_node_health_snapshot_nullable_fields():
    from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
    mapper = sa_inspect(NodeHealthSnapshot)
    nullable_cols = {
        "disk_root_used_gb", "disk_root_total_gb", "disk_root_pct", "disk_root_inodes_pct",
        "mem_total_gb", "mem_available_gb", "mem_used_pct",
        "cpu_load_1m", "cpu_load_5m", "cpu_load_15m",
        "uptime_seconds", "gpu_name", "gpu_vram_mb",
        "cpu_power_mw", "gpu_power_mw", "thermal_pressure", "error",
    }
    for col_name in nullable_cols:
        col = mapper.c[col_name]
        assert col.nullable, f"{col_name} should be nullable"


def test_node_health_snapshot_has_index():
    from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
    index_names = {idx.name for idx in NodeHealthSnapshot.__table__.indexes}
    assert "idx_node_health_node_collected" in index_names


def test_node_health_snapshot_exported_from_models():
    from fleet_platform.models import NodeHealthSnapshot
    assert NodeHealthSnapshot.__tablename__ == "node_health_snapshots"
