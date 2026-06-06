"""Contract tests for #373: both log views use the shared LogPane; width/size applied."""

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DETAIL = (ROOT / "frontend/src/pages/PlaybookJobDetail.tsx").read_text()
MODAL = (ROOT / "frontend/src/pages/PlaybookRunModal.tsx").read_text()
LOGPANE = (ROOT / "frontend/src/lib/LogPane.tsx").read_text()


def test_both_views_use_logpane():
    assert "<LogPane" in DETAIL
    assert "<LogPane" in MODAL


def test_no_duplicated_scroll_pre_in_views():
    # The raw <pre ref=...> log element now lives only in LogPane, not in the views.
    assert "onScroll" not in DETAIL
    assert "onScroll" not in MODAL
    assert "scrollHeight" not in DETAIL
    assert "scrollHeight" not in MODAL


def test_logpane_uses_pure_helper_and_layout_effect():
    assert "isAtBottom" in LOGPANE
    assert "useLayoutEffect" in LOGPANE


def test_logpane_has_jump_to_bottom():
    assert "Jump to bottom" in LOGPANE
    assert "jumpToBottom" in LOGPANE


def test_logpane_text_size_is_sm():
    assert "text-sm" in LOGPANE
    assert "text-xs font-mono" not in LOGPANE  # log text bumped from xs -> sm


def test_widths_increased():
    assert "max-w-7xl" in DETAIL
    assert "max-w-5xl" in MODAL


def test_ansi_colour_preserved():
    # #369 rendering still flows through LogPane.
    assert "AnsiText" in LOGPANE
