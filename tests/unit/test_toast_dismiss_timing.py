"""Unit tests for #159 — toast dismiss timing by type."""
from pathlib import Path

SRC = Path("frontend/src/stores/toastStore.ts").read_text()

def test_error_toast_no_autodismiss():
    """Error toasts must not auto-dismiss (no setTimeout for error type)."""
    # The DISMISS_MS map must have null for error
    assert "error: null" in SRC or "error:null" in SRC, (
        "Error toasts must not auto-dismiss — null delay required"
    )

def test_success_uses_shorter_timeout():
    """Success toasts should dismiss faster than the old 4000ms."""
    assert "3000" in SRC, "Success toasts should use 3000ms dismiss"

def test_warning_uses_longer_timeout():
    """Warning toasts should stay longer than success."""
    assert "6000" in SRC, "Warning toasts should use 6000ms dismiss"

def test_dismiss_ms_map_present():
    """DISMISS_MS lookup map must be present."""
    assert "DISMISS_MS" in SRC, "toastStore must have DISMISS_MS type-to-delay map"
