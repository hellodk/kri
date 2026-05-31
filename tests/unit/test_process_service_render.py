"""Tests for wired process/service tab result rendering (#289 #290)."""


def test_process_tab_polls_task_result():
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    assert "process-task" in content, "Process tab must poll task result"
    assert "processPolling" in content, "Process tab needs polling state"


def test_process_tab_renders_table():
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    assert "cpu_percent" in content or "cpu percent" in content.lower()
    assert "requestProcessAction" in content


def test_service_tab_polls_task_result():
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    assert "service-task" in content, "Service tab must poll task result"
    assert "servicesPolling" in content


def test_service_tab_renders_service_list():
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    assert "serviceList" in content
    assert "requestServiceAction" in content
