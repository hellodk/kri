"""Unit tests for #74 (bulk Salt confirm) and #76 (replace confirm() with modal)."""

import re
from pathlib import Path

DASHBOARD = Path("frontend/src/pages/FleetDashboard.tsx").read_text()
GROUP = Path("frontend/src/pages/GroupExplorer.tsx").read_text()
ALERTS = Path("frontend/src/pages/AlertsPage.tsx").read_text()
NODE = Path("frontend/src/pages/NodeDetail.tsx").read_text()
CONFIRM_COMPONENT = Path("frontend/src/components/ConfirmDialog.tsx").read_text()


def test_no_bare_confirm_calls_remain():
    """No production code should use bare confirm() or window.confirm()."""
    for name, src in [
        ("FleetDashboard", DASHBOARD),
        ("GroupExplorer", GROUP),
        ("AlertsPage", ALERTS),
        ("NodeDetail", NODE),
    ]:
        assert "window.confirm(" not in src, f"{name} must not use window.confirm()"
        # bare confirm( — only in comments or strings is OK
        bare = re.findall(r"(?<!\w)confirm\s*\(", src)
        assert not bare, f"{name} has bare confirm() calls: {bare}"


def test_bulk_salt_state_uses_confirm_dialog():
    assert "ConfirmDialog" in DASHBOARD, "FleetDashboard must use ConfirmDialog for Salt state apply"
    assert "saltStateConfirm" in DASHBOARD or "confirmBulkApply" in DASHBOARD, (
        "FleetDashboard must have confirm state for bulk Salt apply"
    )


def test_confirm_dialog_component_exists():
    assert 'role="dialog"' in CONFIRM_COMPONENT, "ConfirmDialog must have role=dialog"
    assert "aria-modal" in CONFIRM_COMPONENT, "ConfirmDialog must have aria-modal"
    assert "Escape" in CONFIRM_COMPONENT, "ConfirmDialog must handle Escape key"
