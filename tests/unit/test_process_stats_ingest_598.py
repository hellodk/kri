"""#598 — Phase 1a: process-telemetry ingest pipeline unit tests.

Tests (no DB required):
1. Migration 047 exists with module-level revision/down_revision per the #571 guard.
2. ProcessStatsIngestPayload parses valid payloads; collected_at defaults None; ProcessStatItem
   validates with only required fields (pid, name).
3. Endpoint constant _MAX_PROCESSES_PER_PAYLOAD == 250.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "fleet_platform/db/migrations/versions"


# ---------------------------------------------------------------------------
# 1. Migration chain guard for 047
# ---------------------------------------------------------------------------


def _module_assignments(path: Path) -> dict[str, object]:
    """Return module-level simple name=constant assignments from a .py file."""
    tree = ast.parse(path.read_text())
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                out[node.targets[0].id] = "<non-literal>"
    return out


def test_migration_047_exists_with_module_level_ids():
    migration_file = VERSIONS / "047_node_process_stats_hypertable.py"
    assert migration_file.exists(), "Migration 047_node_process_stats_hypertable.py not found"

    assignments = _module_assignments(migration_file)
    assert assignments.get("revision") == "047", (
        f"Expected module-level revision='047', got {assignments.get('revision')!r}"
    )
    assert assignments.get("down_revision") == "046", (
        f"Expected module-level down_revision='046', got {assignments.get('down_revision')!r}"
    )


# ---------------------------------------------------------------------------
# 2. Schema validation
# ---------------------------------------------------------------------------


def test_process_stat_item_minimal():
    from fleet_platform.schemas.ingest import ProcessStatItem

    item = ProcessStatItem(pid=1234, name="python3")
    assert item.pid == 1234
    assert item.name == "python3"
    assert item.cmdline is None
    assert item.cpu_pct is None
    assert item.mem_rss_bytes is None
    assert item.mem_pct is None
    assert item.num_threads is None
    assert item.status is None
    assert item.username is None
    assert item.io_read_bytes is None
    assert item.io_write_bytes is None
    assert item.is_llm is False


def test_process_stat_item_full():
    from fleet_platform.schemas.ingest import ProcessStatItem

    item = ProcessStatItem(
        pid=42,
        name="ollama",
        cmdline="/usr/bin/ollama serve",
        cpu_pct=12.5,
        mem_rss_bytes=1073741824,
        mem_pct=6.3,
        num_threads=8,
        status="running",
        username="root",
        io_read_bytes=204800,
        io_write_bytes=4096,
        is_llm=True,
    )
    assert item.pid == 42
    assert item.is_llm is True
    assert item.mem_rss_bytes == 1073741824


def test_process_stats_payload_minimal():
    from fleet_platform.schemas.ingest import ProcessStatsIngestPayload

    payload = ProcessStatsIngestPayload(
        minion_id="mac-mini-01",
        processes=[{"pid": 1, "name": "launchd"}],
    )
    assert payload.minion_id == "mac-mini-01"
    assert payload.collected_at is None
    assert len(payload.processes) == 1
    assert payload.processes[0].pid == 1


def test_process_stats_payload_collected_at_explicit():
    from datetime import datetime, timezone

    from fleet_platform.schemas.ingest import ProcessStatsIngestPayload

    ts = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    payload = ProcessStatsIngestPayload(
        minion_id="mac-mini-01",
        collected_at=ts,
        processes=[],
    )
    assert payload.collected_at == ts


def test_process_stats_payload_empty_processes_list():
    from fleet_platform.schemas.ingest import ProcessStatsIngestPayload

    payload = ProcessStatsIngestPayload(minion_id="node-x", processes=[])
    assert payload.processes == []


# ---------------------------------------------------------------------------
# 3. Endpoint cap constant
# ---------------------------------------------------------------------------


def test_max_processes_per_payload_constant():
    from fleet_platform.api.routes.ingest import _MAX_PROCESSES_PER_PAYLOAD

    assert _MAX_PROCESSES_PER_PAYLOAD == 250


def test_payload_with_300_processes_validates():
    """Pydantic accepts 300 items — the cap is enforced in the endpoint handler, not the schema."""
    from fleet_platform.schemas.ingest import ProcessStatsIngestPayload

    procs = [{"pid": i, "name": f"proc_{i}"} for i in range(300)]
    payload = ProcessStatsIngestPayload(minion_id="big-node", processes=procs)
    assert len(payload.processes) == 300


@pytest.mark.parametrize(
    "required_only",
    [
        {"pid": 0, "name": "kernel_task"},
        {"pid": 99999, "name": "a" * 255},
    ],
)
def test_process_stat_item_edge_cases(required_only):
    from fleet_platform.schemas.ingest import ProcessStatItem

    item = ProcessStatItem(**required_only)
    assert item.pid == required_only["pid"]
    assert item.name == required_only["name"]
    assert item.is_llm is False
