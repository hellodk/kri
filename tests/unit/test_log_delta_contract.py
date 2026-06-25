# tests/unit/test_log_delta_contract.py
"""Behavioral tests for the playbook log delta-polling feature (#371).

The backend half is exercised by importing the real schema + the pure
``log_delta`` helpers and asserting on their *behaviour* (field presence on the
Pydantic model, and the actual slicing/marker-parsing output). The frontend
half remains source-contract checks (owned by the frontend; a `.tsx/.ts`
scrape cannot be made behavioral from a Python unit test).
"""

from pathlib import Path

from fleet_platform.schemas.playbook import AnsibleJobResponse
from fleet_platform.services.log_delta import slice_from, split_running_marker

ROOT = Path(__file__).parent.parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text()


# ---------------------------------------------------------------------------
# Schema contract — assert on the real Pydantic model, not the source text
# ---------------------------------------------------------------------------


def test_schema_has_stdout_total_len():
    assert "stdout_total_len" in AnsibleJobResponse.model_fields, (
        "AnsibleJobResponse must declare stdout_total_len field"
    )


def test_schema_has_running_task():
    assert "running_task" in AnsibleJobResponse.model_fields, "AnsibleJobResponse must declare running_task field"


def test_schema_delta_fields_optional_ints_and_str():
    """The delta fields must round-trip with their documented types."""
    job = AnsibleJobResponse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "playbook": "site.yml",
            "target_type": "node",
            "target_label": "web-1",
            "extravars": {},
            "status": "running",
            "triggered_by": "alice",
            "started_at": None,
            "completed_at": None,
            "stdout": "hello",
            "rc": None,
            "created_at": "2026-01-01T00:00:00Z",
            "stdout_total_len": 5,
            "running_task": "Install nginx",
        }
    )
    assert job.stdout_total_len == 5
    assert job.running_task == "Install nginx"
    # Defaults to None when omitted (back-compat for non-delta responses).
    minimal = AnsibleJobResponse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "playbook": "site.yml",
            "target_type": "node",
            "target_label": "web-1",
            "extravars": {},
            "status": "queued",
            "triggered_by": "bob",
            "started_at": None,
            "completed_at": None,
            "stdout": None,
            "rc": None,
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    assert minimal.stdout_total_len is None
    assert minimal.running_task is None


# ---------------------------------------------------------------------------
# log_delta service — pure functions, asserted on real output
# ---------------------------------------------------------------------------


def test_split_running_marker_extracts_task_name():
    base, task = split_running_marker("line1\nline2\n\n[running: Gather facts]")
    assert base == "line1\nline2"
    assert task == "Gather facts"


def test_split_running_marker_trailing_whitespace_after_marker():
    base, task = split_running_marker("output\n\n[running: Install pkg]\n  ")
    assert base == "output"
    assert task == "Install pkg"


def test_split_running_marker_no_marker_returns_stdout_unchanged():
    base, task = split_running_marker("just plain output, no marker")
    assert base == "just plain output, no marker"
    assert task is None


def test_split_running_marker_empty_and_none():
    assert split_running_marker("") == ("", None)
    assert split_running_marker(None) == ("", None)


def test_split_running_marker_base_is_append_only_stable_offset():
    """The base (pre-marker) must be identical regardless of which volatile
    task marker is currently appended — that's what makes byte offsets stable."""
    base_text = "TASK 1 ok\nTASK 2 ok"
    b1, _ = split_running_marker(f"{base_text}\n\n[running: TASK 3]")
    b2, _ = split_running_marker(f"{base_text}\n\n[running: TASK 4 with a longer name]")
    assert b1 == b2 == base_text


def test_slice_from_returns_tail():
    assert slice_from("abcdef", 2) == "cdef"


def test_slice_from_at_end_returns_empty():
    assert slice_from("abcdef", 6) == ""


def test_slice_from_past_end_returns_empty():
    assert slice_from("abc", 99) == ""


def test_slice_from_zero_returns_whole_string():
    assert slice_from("abcdef", 0) == "abcdef"


def test_delta_roundtrip_only_returns_new_bytes():
    """End-to-end: a client that already has N bytes of the base only receives
    the newly-appended suffix on the next poll."""
    first_flush = "TASK 1 ok\n\n[running: TASK 2]"
    base1, running1 = split_running_marker(first_flush)
    assert running1 == "TASK 2"
    seen = len(base1)

    second_flush = "TASK 1 ok\nTASK 2 ok\n\n[running: TASK 3]"
    base2, running2 = split_running_marker(second_flush)
    delta = slice_from(base2, seen)
    assert delta == "\nTASK 2 ok"
    assert running2 == "TASK 3"


# ---------------------------------------------------------------------------
# Frontend wiring — source-contract checks (frontend-owned .tsx/.ts; cannot be
# made behavioral from a Python unit test).
# ---------------------------------------------------------------------------


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
