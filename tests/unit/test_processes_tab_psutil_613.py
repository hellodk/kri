"""
Source-contract tests for issue #613:
Processes tab migrated from salt-api on-demand task to psutil read API.
"""

from pathlib import Path

FLEET_TS = Path("frontend/src/api/fleet.ts").read_text()
NODE_DETAIL_TSX = Path("frontend/src/pages/NodeDetail.tsx").read_text()


# ── fleet.ts contracts ──────────────────────────────────────────────────────


def test_fleet_ts_has_processStats_method():
    assert "processStats" in FLEET_TS, "fleet.ts must export a processStats method"


def test_fleet_ts_has_process_stats_path():
    assert "process_stats" in FLEET_TS, "fleet.ts processStats must use the /process_stats path"


def test_fleet_ts_has_ProcessStatsResponse_type():
    assert "ProcessStatsResponse" in FLEET_TS, "fleet.ts must define/export ProcessStatsResponse interface"


def test_fleet_ts_has_ProcessStatRow_type():
    assert "ProcessStatRow" in FLEET_TS, "fleet.ts must define/export ProcessStatRow interface"


def test_fleet_ts_ProcessStatRow_has_is_llm():
    assert "is_llm" in FLEET_TS, "ProcessStatRow must include is_llm field"


def test_fleet_ts_ProcessStatRow_has_mem_rss_bytes():
    assert "mem_rss_bytes" in FLEET_TS, "ProcessStatRow must include mem_rss_bytes field"


def test_fleet_ts_ProcessStatRow_has_cpu_pct():
    assert "cpu_pct" in FLEET_TS, "ProcessStatRow must include cpu_pct field"


# ── NodeDetail.tsx — new data source ───────────────────────────────────────


def test_nodedetal_calls_fleetApi_processStats():
    assert "fleetApi.processStats" in NODE_DETAIL_TSX, "NodeDetail.tsx must call fleetApi.processStats"


def test_nodedetal_uses_cpu_pct():
    assert "cpu_pct" in NODE_DETAIL_TSX, "NodeDetail.tsx must reference cpu_pct (new field name)"


def test_nodedetal_uses_mem_rss_bytes():
    assert "mem_rss_bytes" in NODE_DETAIL_TSX, "NodeDetail.tsx must reference mem_rss_bytes"


def test_nodedetal_uses_is_llm():
    assert "is_llm" in NODE_DETAIL_TSX, "NodeDetail.tsx must reference is_llm for LLM highlighting"


def test_nodedetal_uses_ist_timezone():
    # #796/#877: NodeDetail no longer hardcodes a timezone. Date rendering (and
    # the timezone suffix) is delegated to the shared formatIST/formatISTDate
    # helper, which formats in the viewer's local timezone.
    assert "formatIST" in NODE_DETAIL_TSX, "NodeDetail.tsx must render dates via the formatIST helper"


def test_nodedetal_has_ist_suffix():
    # The timezone suffix is now produced by the formatIST helper rather than a
    # literal ' IST' string embedded in the page (#796/#877).
    assert "formatIST" in NODE_DETAIL_TSX, "NodeDetail.tsx must use formatIST so timestamps carry a timezone suffix"


# ── NodeDetail.tsx — old data source REMOVED ──────────────────────────────


def test_nodedetal_no_old_processes_read_path():
    old_path = "/api/v1/nodes/${nodeId}/processes`"
    assert old_path not in NODE_DETAIL_TSX, "NodeDetail.tsx must not contain the old salt-task read path /processes"


def test_nodedetal_no_processTaskId_state():
    assert "processTaskId" not in NODE_DETAIL_TSX, (
        "NodeDetail.tsx must not use processTaskId state (old salt-polling approach removed)"
    )


# ── NodeDetail.tsx — controls RETAINED ─────────────────────────────────────


def test_nodedetal_retains_requestProcessAction():
    assert "requestProcessAction" in NODE_DETAIL_TSX, (
        "requestProcessAction function must be retained for Stop/Suspend/Resume"
    )


def test_nodedetal_retains_process_stop():
    assert "process_stop" in NODE_DETAIL_TSX, "process_stop action must be retained"


def test_nodedetal_retains_process_suspend():
    assert "process_suspend" in NODE_DETAIL_TSX, "process_suspend action must be retained"


def test_nodedetal_retains_process_resume():
    assert "process_resume" in NODE_DETAIL_TSX, "process_resume action must be retained"
