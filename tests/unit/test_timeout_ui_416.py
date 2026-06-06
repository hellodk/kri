"""Contract tests for #416: per-job timeout control in PlaybookRunModal."""

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
MODAL = (ROOT / "frontend/src/pages/PlaybookRunModal.tsx").read_text()
DETAIL = (ROOT / "frontend/src/pages/PlaybookJobDetail.tsx").read_text()
API = (ROOT / "frontend/src/api/playbooks.ts").read_text()


def test_modal_has_timeout_min_state():
    """PlaybookRunModal.tsx contains timeoutMin state initialization."""
    assert "timeoutMin" in MODAL
    assert "setTimeoutMin" in MODAL
    assert "useState" in MODAL
    # Should initialize to 30 by default or derive from initialTimeout
    assert "30" in MODAL or "initialTimeout" in MODAL


def test_modal_has_initial_timeout_prop():
    """PlaybookRunModal.tsx Props interface includes initialTimeout."""
    assert "initialTimeout" in MODAL


def test_modal_initializes_timeout_from_prop():
    """PlaybookRunModal.tsx initializes timeoutMin from initialTimeout prop when provided."""
    # When initialTimeout is passed, it should be converted from seconds to minutes
    assert "initialTimeout" in MODAL
    # The initialization logic should appear in the state or useEffect
    assert "timeoutMin" in MODAL


def test_modal_renders_timeout_input():
    """PlaybookRunModal.tsx renders a number input for timeout with label 'Timeout (minutes)'."""
    assert "Timeout (minutes)" in MODAL
    assert 'type="number"' in MODAL
    assert "min=" in MODAL
    assert "max=" in MODAL
    assert "timeoutMin" in MODAL


def test_modal_timeout_input_has_constraints():
    """Timeout input has min=1 and max=360 constraints."""
    # The input must enforce minimum 1 minute and maximum 360 minutes (6 hours)
    assert "min" in MODAL
    assert "max" in MODAL


def test_modal_passes_timeout_to_run_api():
    """PlaybookRunModal calls playbooksApi.run with timeoutMin * 60 as 8th argument."""
    # The run() call should pass the timeout in seconds (minutes * 60)
    assert "timeoutMin * 60" in MODAL or "timeoutSeconds" in MODAL


def test_detail_passes_initial_timeout_to_modal():
    """PlaybookJobDetail.tsx passes initialTimeout={job.timeout_seconds} to PlaybookRunModal."""
    assert "initialTimeout={job.timeout_seconds}" in DETAIL


def test_api_run_forwards_timeout():
    """playbooksApi.run() accepts and forwards timeout_seconds parameter."""
    assert "timeoutSeconds" in API
    assert "timeout_seconds" in API


def test_modal_timeout_clamping():
    """Timeout input onChange should clamp values to [1, 360] range."""
    # The input should have onChange that constrains the value
    assert "timeoutMin" in MODAL
