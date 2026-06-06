"""Contract tests for #369: both log views render via the ANSI parser, safely."""

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DETAIL = (ROOT / "frontend/src/pages/PlaybookJobDetail.tsx").read_text()
MODAL = (ROOT / "frontend/src/pages/PlaybookRunModal.tsx").read_text()
ANSI_TEXT = (ROOT / "frontend/src/lib/AnsiText.tsx").read_text()
LOGPANE = (ROOT / "frontend/src/lib/LogPane.tsx").read_text()


def test_views_render_via_logpane_which_uses_ansitext():
    # Post-#373: both views delegate log rendering to the shared LogPane, which renders ANSI.
    assert "<LogPane" in DETAIL
    assert "<LogPane" in MODAL
    assert "AnsiText" in LOGPANE


def test_no_dangerously_set_inner_html():
    # Remote-host output must never be injected as raw HTML (match real JSX usage, not prose).
    for src in (DETAIL, MODAL, ANSI_TEXT, LOGPANE):
        assert "dangerouslySetInnerHTML={" not in src


def test_stripansi_removed_from_modal():
    assert "stripAnsi" not in MODAL


def test_log_pane_default_text_is_neutral_gray():
    # Green now means 'ok' inside coloured output; the shared log <pre> default must be neutral.
    assert "bg-gray-950 text-gray-300" in LOGPANE


def test_uses_layout_effect_for_autoscroll():
    assert "useLayoutEffect" in LOGPANE


def test_parser_memoised():
    assert "useMemo" in ANSI_TEXT
