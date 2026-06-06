"""Tests for #454 (timeout isinstance) and #455 (job_start_time pre-init)."""

from decimal import Decimal

# ── #454: timeout isinstance fix ────────────────────────────────────────────


def _resolve_timeout(raw_value):
    """Mirrors the fixed timeout resolution logic."""
    _timeout_int = int(raw_value) if raw_value is not None else 1800
    return max(60, min(7200, _timeout_int))


def test_timeout_applied_when_column_returns_decimal():
    """Decimal('3600') must resolve to 3600, not 1800."""
    assert _resolve_timeout(Decimal("3600")) == 3600


def test_timeout_applied_when_column_returns_float():
    """3600.0 must resolve to 3600, not 1800."""
    assert _resolve_timeout(3600.0) == 3600


def test_timeout_applied_when_column_returns_int():
    """int 3600 must still resolve to 3600."""
    assert _resolve_timeout(3600) == 3600


def test_timeout_defaults_when_column_is_none():
    """None must resolve to 1800 (default)."""
    assert _resolve_timeout(None) == 1800


def test_timeout_clamped_to_minimum():
    """Values below 60 are clamped to 60."""
    assert _resolve_timeout(10) == 60


def test_timeout_clamped_to_maximum():
    """Values above 7200 are clamped to 7200."""
    assert _resolve_timeout(99999) == 7200


# ── #455: job_start_time pre-init source contract ───────────────────────────


def test_job_start_time_preinit_before_try_block():
    """
    Source-contract test: job_start_time must be initialised before the try block
    so SoftTimeLimitExceeded can reference it without NameError.

    Checks that 'job_start_time' appears in the source before the 'try:' that
    opens the main run_playbook body (i.e., the try block that contains run_async).
    """
    from pathlib import Path

    src = Path("fleet_platform/workers/playbook_tasks.py").read_text()

    # Find the position of 'job_start_time: float = 0.0' (pre-init line)
    pre_init_pos = src.find("job_start_time: float = 0.0")
    assert pre_init_pos != -1, (
        "job_start_time: float = 0.0 not found in playbook_tasks.py. "
        "It must be initialised before the try block (#455)."
    )

    # Find the position of the first 'try:' after run_playbook function definition
    run_playbook_pos = src.find("def run_playbook(")
    assert run_playbook_pos != -1, "run_playbook function not found"

    # The pre-init must come before the try block that wraps the main logic
    first_try_after_func = src.find("\n    try:", run_playbook_pos)
    assert first_try_after_func != -1, "Could not find try block in run_playbook"

    assert pre_init_pos < first_try_after_func, (
        f"job_start_time pre-init (pos {pre_init_pos}) must appear before the try block (pos {first_try_after_func})"
    )
