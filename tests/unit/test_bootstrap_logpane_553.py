"""
Issue #553 — bootstrap log view must use LogPane (not a bare <pre>) for
auto-follow, larger height, and ANSI rendering parity with the executions log.

These tests are source-code assertions: they read NodeDetail.tsx and verify
the structural constraints without running a browser or build step.
"""

from pathlib import Path

NODEFILE = Path(__file__).parent.parent.parent / "frontend" / "src" / "pages" / "NodeDetail.tsx"


def _source() -> str:
    return NODEFILE.read_text()


def test_nodefile_exists():
    """Sanity check — the file must be present."""
    assert NODEFILE.exists(), f"NodeDetail.tsx not found at {NODEFILE}"


def test_imports_logpane_not_ansitext():
    """LogPane is imported; AnsiText is no longer imported (it became unused)."""
    src = _source()
    assert "import { LogPane } from '../lib/LogPane'" in src, "NodeDetail.tsx must import LogPane from '../lib/LogPane'"
    assert "import { AnsiText } from '../lib/AnsiText'" not in src, (
        "AnsiText import must be removed — it is no longer used directly"
    )


def test_bootstrap_log_uses_logpane():
    """The bootstrap live-log section must render via <LogPane."""
    src = _source()
    assert "<LogPane" in src, "NodeDetail.tsx must contain at least one <LogPane usage"

    # The live bootstrap block passes node.bootstrap_logs as raw
    assert "raw={node.bootstrap_logs ?? ''}" in src, (
        "LogPane must receive raw={node.bootstrap_logs ?? ''} for the live bootstrap log"
    )


def test_bootstrap_log_no_max_h_48_pre():
    """The old max-h-48 pre wrapping the bootstrap_logs AnsiText must be gone.

    Two other unrelated <pre> elements in the file legitimately keep max-h-48
    (quick-action stdout/stderr blocks), so we check that no line combining
    max-h-48 and bootstrap_logs remains.
    """
    src = _source()
    # The pre element that previously wrapped AnsiText + bootstrap_logs must not exist
    lines = src.splitlines()
    offending = [line for line in lines if "max-h-48" in line and "bootstrap_logs" in line]
    assert not offending, (
        "A max-h-48 element still references bootstrap_logs; it must be replaced by a sized LogPane container"
    )


def test_bootstrap_logpane_is_live_while_bootstrapping():
    """isLive is tied to bootstrap_status === 'bootstrapping'."""
    src = _source()
    assert "isLive={node.bootstrap_status === 'bootstrapping'}" in src, (
        "LogPane must receive isLive={node.bootstrap_status === 'bootstrapping'} "
        "so auto-follow is active only while bootstrapping"
    )


def test_history_expanded_stdout_uses_logpane():
    """The bootstrap-run history expanded stdout must also use LogPane."""
    src = _source()
    assert "raw={expandedRun.ansible_stdout ?? ''}" in src, (
        "Bootstrap history expanded stdout must render via LogPane with raw={expandedRun.ansible_stdout ?? ''}"
    )
