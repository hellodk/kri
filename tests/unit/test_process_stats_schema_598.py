"""Schema validation for process-telemetry ingest payloads (#598)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fleet_platform.schemas.ingest import (
    MAX_PROCESSES_PER_PAYLOAD,
    ProcessStatItem,
    ProcessStatsIngestPayload,
)


def _proc(pid: int = 1) -> dict:
    return {
        "pid": pid,
        "name": "python",
        "cpu_pct": 1.5,
        "mem_rss_bytes": 1048576,
        "mem_pct": 0.5,
        "num_threads": 4,
    }


def test_minimal_item_valid_with_optional_fields_defaulted():
    item = ProcessStatItem(**_proc())
    assert item.cmdline is None
    assert item.status is None
    assert item.io_read_bytes is None
    assert item.is_llm is False


def test_collected_at_optional_defaults_to_none():
    payload = ProcessStatsIngestPayload(minion_id="n1.local", processes=[ProcessStatItem(**_proc())])
    assert payload.collected_at is None


def test_collected_at_preserved_when_supplied():
    ts = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    payload = ProcessStatsIngestPayload(minion_id="n1.local", collected_at=ts, processes=[])
    assert payload.collected_at == ts


def test_processes_defaults_to_empty_list():
    payload = ProcessStatsIngestPayload(minion_id="n1.local")
    assert payload.processes == []


def test_cap_under_limit_keeps_all():
    procs = [ProcessStatItem(**_proc(i)) for i in range(10)]
    payload = ProcessStatsIngestPayload(minion_id="n1.local", processes=procs)
    kept, dropped = payload.capped_processes()
    assert len(kept) == 10
    assert dropped == 0


def test_cap_at_limit_keeps_all():
    procs = [ProcessStatItem(**_proc(i)) for i in range(MAX_PROCESSES_PER_PAYLOAD)]
    payload = ProcessStatsIngestPayload(minion_id="n1.local", processes=procs)
    kept, dropped = payload.capped_processes()
    assert len(kept) == MAX_PROCESSES_PER_PAYLOAD
    assert dropped == 0


def test_cap_over_limit_truncates_and_reports_overflow():
    overflow = 37
    procs = [ProcessStatItem(**_proc(i)) for i in range(MAX_PROCESSES_PER_PAYLOAD + overflow)]
    payload = ProcessStatsIngestPayload(minion_id="n1.local", processes=procs)
    kept, dropped = payload.capped_processes()
    assert len(kept) == MAX_PROCESSES_PER_PAYLOAD
    assert dropped == overflow
    # First 250 kept in order — no silent reshuffle.
    assert [p.pid for p in kept] == list(range(MAX_PROCESSES_PER_PAYLOAD))


def test_missing_required_field_rejected():
    bad = _proc()
    del bad["cpu_pct"]
    with pytest.raises(ValidationError):
        ProcessStatItem(**bad)
