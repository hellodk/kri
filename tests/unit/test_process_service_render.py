"""Tests for wired process/service tab result rendering (#289 #290)."""


def test_process_tab_reads_psutil_api():
    # #613: the Processes tab view moved from the salt-api on-demand task to the
    # psutil read API. It must use fleetApi.processStats and no longer poll a task.
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    assert "fleetApi.processStats" in content, "Process tab must read from the psutil process_stats API"
    assert "process-stats" in content, "Process tab needs the process-stats query"
    assert "process-task" not in content, "old salt-task polling must be removed from the Processes tab"


def test_process_tab_renders_table():
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    # #613: new fields from the psutil read API + LLM highlight, control retained.
    assert "cpu_pct" in content, "Process table must render the psutil cpu_pct field"
    assert "is_llm" in content, "Process table must highlight LLM/exo processes"
    assert "requestProcessAction" in content


def test_service_tab_polls_task_result():
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    assert "service-task" in content, "Service tab must poll task result"
    assert "servicesPolling" in content


def test_service_tab_renders_service_list():
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    assert "serviceList" in content
    assert "requestServiceAction" in content
