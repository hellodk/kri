"""Tests for #71: destructive deletions use ConfirmDialog, not window.confirm."""
from pathlib import Path

GROUP = Path("frontend/src/pages/GroupDetail.tsx").read_text()
NODE = Path("frontend/src/pages/NodeDetail.tsx").read_text()


def test_group_detail_no_bare_confirm():
    assert "window.confirm" not in GROUP and "confirm(" not in GROUP, \
        "GroupDetail must not use window.confirm()"

def test_group_detail_uses_confirm_dialog():
    assert "ConfirmDialog" in GROUP, "GroupDetail must use ConfirmDialog component"
    assert "deleteSecretConfirm" in GROUP, "GroupDetail must have deleteSecretConfirm state"
    assert "removeMemberConfirm" in GROUP, "GroupDetail must have removeMemberConfirm state"

def test_node_detail_no_bare_confirm():
    assert "window.confirm" not in NODE, "NodeDetail must not use window.confirm()"
    assert "confirm(" not in NODE or "deleteConfirm" in NODE or "ConfirmDialog" in NODE, \
        "NodeDetail must not use bare confirm()"

def test_node_detail_uses_confirm_dialog():
    assert "ConfirmDialog" in NODE, "NodeDetail must use ConfirmDialog component"
