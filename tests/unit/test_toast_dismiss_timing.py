"""Unit tests for #159 — toast dismiss timing by type."""

from pathlib import Path

SRC = Path("frontend/src/stores/toastStore.ts").read_text()


def test_error_toast_autodismiss_8s():
    """Error toasts auto-dismiss after 8s — #688 superseded #159's never-dismiss,
    pairing the longest timeout with a slow fade + manual close button."""
    assert "error: 8000" in SRC or "error:8000" in SRC, "Error toasts should auto-dismiss after 8000ms (#688)"


def test_success_uses_shorter_timeout():
    """Success toasts should dismiss faster than the old 4000ms."""
    assert "3000" in SRC, "Success toasts should use 3000ms dismiss"


def test_warning_uses_longer_timeout():
    """Warning toasts should stay longer than success."""
    assert "6000" in SRC, "Warning toasts should use 6000ms dismiss"


def test_dismiss_ms_map_present():
    """DISMISS_MS lookup map must be present."""
    assert "DISMISS_MS" in SRC, "toastStore must have DISMISS_MS type-to-delay map"
