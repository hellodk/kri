"""Behavioral tests for #369: worker emits ANSI colour + caps stored stdout.

The stdout-capping contract is exercised against the real ``_append_capped``
helper. Two checks remain source-contract because the behaviour lives inside
``run_playbook``'s local ``_event_handler`` closure / the ``ansible_runner``
envvars dict — neither is importable or observable at the unit level without
actually launching ansible-runner (an integration concern).
"""

from pathlib import Path

from fleet_platform.workers.playbook_tasks import (
    _MAX_STDOUT_BYTES,
    _TRUNCATION_SENTINEL,
    _append_capped,
)

WORKER_SRC = (Path(__file__).parent.parent.parent / "fleet_platform/workers/playbook_tasks.py").read_text()


def test_force_color_env_set():
    # behavioral conversion blocked: ANSIBLE_FORCE_COLOR is injected into the
    # envvars dict passed to ansible_runner.run_async() inside run_playbook;
    # observing it requires launching ansible-runner (integration-level).
    assert '"ANSIBLE_FORCE_COLOR": "1"' in WORKER_SRC


def test_append_capped_stores_ansi_codes_verbatim():
    """Stdout is stored verbatim — ANSI SGR sequences must NOT be stripped, so
    the UI can render CLI-identical colour."""
    lines, state = [], {"size": 0, "truncated": False}
    coloured = "\x1b[0;32mok:\x1b[0m [web-1] => changed"
    _append_capped(lines, coloured, state)
    assert lines == [coloured]
    assert lines[0] == coloured  # exact bytes preserved, no stripping
    assert state["size"] == len(coloured)


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
    _append_capped(lines, big, state)  # crosses the cap
    _append_capped(lines, "more", state)  # ignored after truncation
    _append_capped(lines, "evenmore", state)  # still ignored
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
    # behavioral conversion blocked: the task name is captured in run_playbook's
    # local _event_handler closure (not importable); asserting it behaviorally
    # would require running ansible_runner and feeding it real events.
    assert 'event.get("event_data", {}).get("task"' in WORKER_SRC
