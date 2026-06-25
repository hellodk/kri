"""
Source-contract tests for issue #613:
Processes tab migrated from salt-api on-demand task to psutil read API.
"""

from pathlib import Path

FLEET_TS = Path("frontend/src/api/fleet.ts").read_text()
# #787: NodeDetail.tsx was decomposed into per-tab panels. The Processes tab
# now lives in its own component; its source-contract assertions read from there.
PROCESSES_TAB_TSX = Path("frontend/src/pages/nodeDetail/ProcessesTab.tsx").read_text()


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


# ── ProcessesTab.tsx — new data source ─────────────────────────────────────


def test_nodedetal_calls_fleetApi_processStats():
    assert "fleetApi.processStats" in PROCESSES_TAB_TSX, "ProcessesTab.tsx must call fleetApi.processStats"


def test_nodedetal_uses_cpu_pct():
    assert "cpu_pct" in PROCESSES_TAB_TSX, "ProcessesTab.tsx must reference cpu_pct (new field name)"


def test_nodedetal_uses_mem_rss_bytes():
    assert "mem_rss_bytes" in PROCESSES_TAB_TSX, "ProcessesTab.tsx must reference mem_rss_bytes"


def test_nodedetal_uses_is_llm():
    assert "is_llm" in PROCESSES_TAB_TSX, "ProcessesTab.tsx must reference is_llm for LLM highlighting"


def test_nodedetal_uses_ist_timezone():
    # #796/#877: the Processes tab no longer hardcodes a timezone. The "as of"
    # collection timestamp is rendered via the shared formatLocalDateTime helper,
    # which formats in the viewer's local timezone.
    assert "formatLocalDateTime" in PROCESSES_TAB_TSX, (
        "ProcessesTab.tsx must render the collected_at timestamp via the formatLocalDateTime helper"
    )


def test_nodedetal_has_ist_suffix():
    # The timezone suffix is produced by the formatLocalDateTime helper rather
    # than a literal ' IST' string embedded in the page (#796/#877).
    assert "formatLocalDateTime" in PROCESSES_TAB_TSX, (
        "ProcessesTab.tsx must use formatLocalDateTime so the timestamp carries a local-timezone rendering"
    )


# ── ProcessesTab.tsx — old data source REMOVED ────────────────────────────


def test_nodedetal_no_old_processes_read_path():
    old_path = "/api/v1/nodes/${nodeId}/processes`"
    assert old_path not in PROCESSES_TAB_TSX, "ProcessesTab.tsx must not contain the old salt-task read path /processes"


def test_nodedetal_no_processTaskId_state():
    assert "processTaskId" not in PROCESSES_TAB_TSX, (
        "ProcessesTab.tsx must not use processTaskId state (old salt-polling approach removed)"
    )


# ── ProcessesTab.tsx — controls RETAINED ───────────────────────────────────


def test_nodedetal_retains_requestProcessAction():
    assert "requestProcessAction" in PROCESSES_TAB_TSX, (
        "requestProcessAction function must be retained for Stop/Suspend/Resume"
    )


def test_nodedetal_retains_process_stop():
    assert "process_stop" in PROCESSES_TAB_TSX, "process_stop action must be retained"


def test_nodedetal_retains_process_suspend():
    assert "process_suspend" in PROCESSES_TAB_TSX, "process_suspend action must be retained"


def test_nodedetal_retains_process_resume():
    assert "process_resume" in PROCESSES_TAB_TSX, "process_resume action must be retained"
