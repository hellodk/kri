# tests/unit/test_llm_context_degradation_637.py
"""
Tests for #637 Fix 3 — graceful context degradation in submit_query.

Source-contract assertions: build_fleet_context is wrapped in a try/except
and a degraded fallback assigns system_prompt in the except clause.
Uses Path(__file__) for relative path resolution — never absolute paths.
"""

from pathlib import Path


def _read_llm_route_source() -> str:
    route_path = Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "llm.py"
    return route_path.read_text()


def test_build_fleet_context_wrapped_in_try():
    """build_fleet_context call must appear inside a try block."""
    src = _read_llm_route_source()
    # Both must appear in the source
    assert "build_fleet_context" in src
    assert "try:" in src


def test_degraded_fallback_assigns_system_prompt():
    """An except clause must assign system_prompt as the degraded fallback."""
    src = _read_llm_route_source()
    # Verify the degraded fallback text is present
    assert "fleet context was temporarily unavailable" in src


def test_logger_exception_called_on_context_failure():
    """logger.exception must be called when build_fleet_context fails."""
    src = _read_llm_route_source()
    assert "logger.exception" in src
    assert "build_fleet_context failed" in src


def test_degraded_context_mentions_kri():
    """Degraded fallback must still identify the platform as kri."""
    src = _read_llm_route_source()
    assert "kri, a fleet management platform" in src
