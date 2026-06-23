"""Unit tests for the artifact diff service (#713)."""

from __future__ import annotations

from fleet_platform.services.artifact_diff import diff_text


def test_new_file_is_marked_new():
    res = diff_text(None, "line1\nline2\n")
    assert res.is_new is True
    assert res.added == 2
    assert res.removed == 0


def test_empty_old_is_new():
    res = diff_text("", "a\n")
    assert res.is_new is True


def test_modification_counts():
    old = "a\nb\nc\n"
    new = "a\nB\nc\nd\n"
    res = diff_text(old, new)
    assert res.is_new is False
    assert res.added == 2  # B and d
    assert res.removed == 1  # b
    assert "+B" in res.unified
    assert "-b" in res.unified


def test_identical_has_no_changes():
    res = diff_text("x\n", "x\n")
    assert res.added == 0 and res.removed == 0
    assert res.unified == ""
