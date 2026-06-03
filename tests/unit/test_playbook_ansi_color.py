"""Tests for #369: worker emits ANSI colour + caps stored stdout."""
from pathlib import Path

from fleet_platform.workers.playbook_tasks import (
    _MAX_STDOUT_BYTES,
    _TRUNCATION_SENTINEL,
    _append_capped,
)

WORKER_SRC = (
    Path(__file__).parent.parent.parent / "fleet_platform/workers/playbook_tasks.py"
).read_text()


def test_force_color_env_set():
    assert '"ANSIBLE_FORCE_COLOR": "1"' in WORKER_SRC


def test_stdout_stored_verbatim_no_ansi_strip():
    # Capture path appends event stdout verbatim; no ANSI-stripping regex on the worker.
    assert "_append_capped(stdout_lines, msg, _trunc_ref)" in WORKER_SRC
    assert r"\x1b[" not in WORKER_SRC  # no SGR-stripping regex on the capture path


def test_append_capped_appends_normally():
    lines, state = [], {"size": 0, "truncated": False}
    _append_capped(lines, "hello", state)
    _append_capped(lines, "world", state)
    assert lines == ["hello", "world"]
    assert state["size"] == 10
    assert state["truncated"] is False


def test_append_capped_adds_sentinel_once_and_stops():
    lines, state = [], {"size": 0, "truncated": False}
    big = "x" * (_MAX_STDOUT_BYTES + 1)
    _append_capped(lines, big, state)        # crosses the cap
    _append_capped(lines, "more", state)     # ignored after truncation
    _append_capped(lines, "evenmore", state) # still ignored
    assert state["truncated"] is True
    assert lines[-1] == _TRUNCATION_SENTINEL
    assert lines.count(_TRUNCATION_SENTINEL) == 1
    assert "more" not in lines
    assert "evenmore" not in lines


def test_append_capped_just_under_cap_keeps_appending():
    lines, state = [], {"size": 0, "truncated": False}
    _append_capped(lines, "y" * (_MAX_STDOUT_BYTES - 10), state)
    assert state["truncated"] is False
    _append_capped(lines, "z" * 5, state)
    assert state["truncated"] is False
    assert _TRUNCATION_SENTINEL not in lines


def test_task_name_extracted_from_event_data_not_stdout():
    # Task name (for the [running: ...] marker) must come from structured event_data,
    # so colourised stdout never corrupts it.
    assert 'event.get("event_data", {}).get("task"' in WORKER_SRC
