"""Tests for wired process/service tab result rendering (#289 #290)."""

from pathlib import Path

# #787: NodeDetail was decomposed into the pages/nodeDetail/ package; the
# process/service tab markup now lives in extracted tab components. Read the
# shell + the package together so these source assertions still apply.
_PAGES = Path("frontend/src/pages")


def _node_detail_surface() -> str:
    parts = [(_PAGES / "NodeDetail.tsx").read_text()]
    pkg = _PAGES / "nodeDetail"
    if pkg.is_dir():
        parts.extend(p.read_text() for p in sorted(pkg.glob("*.tsx")))
        parts.extend(p.read_text() for p in sorted(pkg.glob("*.ts")))
    return "\n".join(parts)


def test_process_tab_reads_psutil_api():
    # #613: the Processes tab view moved from the salt-api on-demand task to the
    # psutil read API. It must use fleetApi.processStats and no longer poll a task.
    content = _node_detail_surface()
    assert "fleetApi.processStats" in content, "Process tab must read from the psutil process_stats API"
    assert "process-stats" in content, "Process tab needs the process-stats query"
    assert "process-task" not in content, "old salt-task polling must be removed from the Processes tab"


def test_process_tab_renders_table():
    content = _node_detail_surface()
    # #613: new fields from the psutil read API + LLM highlight, control retained.
    assert "cpu_pct" in content, "Process table must render the psutil cpu_pct field"
    assert "is_llm" in content, "Process table must highlight LLM/exo processes"
    assert "requestProcessAction" in content


def test_service_tab_polls_task_result():
    content = _node_detail_surface()
    assert "service-task" in content, "Service tab must poll task result"
    assert "servicesPolling" in content


def test_service_tab_renders_service_list():
    content = _node_detail_surface()
    assert "serviceList" in content
    assert "requestServiceAction" in content
