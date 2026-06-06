# tests/unit/test_log_delta_contract.py
"""Contract tests: verify schema + frontend interface stay in sync (#371)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_schema_has_stdout_total_len():
    src = _read("fleet_platform/schemas/playbook.py")
    assert "stdout_total_len" in src, "AnsibleJobResponse must declare stdout_total_len field"


def test_schema_has_running_task():
    src = _read("fleet_platform/schemas/playbook.py")
    assert "running_task" in src, "AnsibleJobResponse must declare running_task field"


def test_ts_interface_has_stdout_total_len():
    src = _read("frontend/src/api/playbooks.ts")
    assert "stdout_total_len" in src, "AnsibleJob TS interface must declare stdout_total_len"


def test_ts_interface_has_running_task():
    src = _read("frontend/src/api/playbooks.ts")
    assert "running_task" in src, "AnsibleJob TS interface must declare running_task"


def test_ts_api_has_from_byte():
    src = _read("frontend/src/api/playbooks.ts")
    assert "from_byte" in src, "playbooksApi.getJob must pass from_byte query param"


def test_job_detail_wired_for_delta():
    src = _read("frontend/src/pages/PlaybookJobDetail.tsx")
    assert "stdout_total_len" in src, "PlaybookJobDetail must handle stdout_total_len (delta wiring)"


def test_run_modal_wired_for_delta():
    src = _read("frontend/src/pages/PlaybookRunModal.tsx")
    assert "stdout_total_len" in src, "PlaybookRunModal must handle stdout_total_len (delta wiring)"
