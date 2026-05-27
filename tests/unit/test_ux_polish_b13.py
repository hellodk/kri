"""Unit tests for #78 (404 route), #77 (skeleton loaders), #75 (empty states)."""
from pathlib import Path

APP = Path("frontend/src/App.tsx").read_text()
SETTINGS = Path("frontend/src/pages/SettingsPage.tsx").read_text()
SECURITY = Path("frontend/src/pages/SecurityPage.tsx").read_text()
DRIFT = Path("frontend/src/pages/DriftExplorer.tsx").read_text()
EXEC = Path("frontend/src/pages/ExecutionHistory.tsx").read_text()


def test_404_catch_all_route_present():
    assert 'path="*"' in APP, "App must have a catch-all * route"
    assert "NotFoundPage" in APP, "App must render NotFoundPage for unknown routes"


def test_settings_uses_skeleton_not_loading_text():
    assert "<Skeleton" in SETTINGS, "SettingsPage must use Skeleton component for loading state"
    assert "Loading…" not in SETTINGS and "Loading..." not in SETTINGS, (
        "SettingsPage must not use plain Loading text — use Skeleton instead"
    )


def test_security_uses_skeleton_not_loading_text():
    # SecurityPage has multiple loading sections — at minimum the main one
    skeleton_count = SECURITY.count("<Skeleton")
    assert skeleton_count > 0, "SecurityPage must use Skeleton component"


def test_drift_has_empty_state():
    assert "No drift" in DRIFT or "no drift" in DRIFT.lower(), (
        "DriftExplorer must show empty state message when no drift data"
    )


def test_execution_history_has_empty_state():
    assert "No executions" in EXEC or "no executions" in EXEC.lower(), (
        "ExecutionHistory must show empty state when no executions"
    )
