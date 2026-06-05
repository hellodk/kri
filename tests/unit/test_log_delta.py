# tests/unit/test_log_delta.py
"""Unit tests for fleet_platform.services.log_delta (#371)."""


from fleet_platform.services.log_delta import slice_from, split_running_marker

# ---------------------------------------------------------------------------
# split_running_marker
# ---------------------------------------------------------------------------


def test_split_none():
    assert split_running_marker(None) == ("", None)


def test_split_empty():
    assert split_running_marker("") == ("", None)


def test_split_no_marker():
    text = "task1\ntask2\ntask3"
    assert split_running_marker(text) == (text, None)


def test_split_with_marker():
    text = "abc\n\n[running: Install salt]"
    base, task = split_running_marker(text)
    assert base == "abc"
    assert task == "Install salt"


def test_split_marker_trailing_whitespace():
    text = "abc\n\n[running: Install salt]  \n"
    base, task = split_running_marker(text)
    assert base == "abc"
    assert task == "Install salt"


def test_split_marker_trailing_newline():
    text = "abc\n\n[running: Deploy config]\n\n"
    base, task = split_running_marker(text)
    assert base == "abc"
    assert task == "Deploy config"


def test_split_marker_task_with_spaces():
    text = "line one\nline two\n\n[running: Gather Facts on hosts]"
    base, task = split_running_marker(text)
    assert base == "line one\nline two"
    assert task == "Gather Facts on hosts"


# ---------------------------------------------------------------------------
# slice_from
# ---------------------------------------------------------------------------


def test_slice_from_zero():
    assert slice_from("hello", 0) == "hello"


def test_slice_from_mid():
    assert slice_from("hello", 3) == "lo"


def test_slice_from_at_end():
    assert slice_from("hello", 5) == ""


def test_slice_from_beyond_end():
    assert slice_from("hello", 99) == ""


def test_slice_from_one():
    assert slice_from("hello", 1) == "ello"


# ---------------------------------------------------------------------------
# ANSI sequences never split at a reported boundary
# ---------------------------------------------------------------------------


def test_ansi_not_split_at_boundary():
    """When base grows by appending a complete new line, slicing at the old
    boundary must return only complete escape sequences."""
    base1 = "\x1b[32mok\x1b[0m"
    extra = "\n\x1b[33mchanged\x1b[0m"
    base2 = base1 + extra
    delta = slice_from(base2, len(base1))
    assert delta == extra
    # Verify no partial escape in the delta
    assert delta.startswith("\n\x1b[")


def test_ansi_empty_when_at_boundary():
    base = "\x1b[32mok\x1b[0m"
    assert slice_from(base, len(base)) == ""
