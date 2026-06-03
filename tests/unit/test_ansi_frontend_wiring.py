"""Contract tests for #369: both log views render via the ANSI parser, safely."""
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DETAIL = (ROOT / "frontend/src/pages/PlaybookJobDetail.tsx").read_text()
MODAL = (ROOT / "frontend/src/pages/PlaybookRunModal.tsx").read_text()
ANSI_TEXT = (ROOT / "frontend/src/lib/AnsiText.tsx").read_text()


def test_both_views_use_ansitext():
    assert "<AnsiText raw={job.stdout} />" in DETAIL
    assert "AnsiText raw={stdout}" in MODAL


def test_no_dangerously_set_inner_html():
    # Remote-host output must never be injected as raw HTML (match real JSX usage, not prose).
    for src in (DETAIL, MODAL, ANSI_TEXT):
        assert "dangerouslySetInnerHTML={" not in src


def test_stripansi_removed_from_modal():
    assert "stripAnsi" not in MODAL


def test_log_pane_default_text_is_neutral_gray():
    # Green now means 'ok' inside coloured output; the log <pre> default must be neutral.
    # (The separate "Command" box keeps its terminal-green prompt styling — not the log pane.)
    assert 'bg-gray-950 text-gray-300 p-4 overflow-auto leading-relaxed whitespace-pre-wrap h-full' in DETAIL
    assert 'flex-1 text-xs font-mono bg-gray-950 text-gray-300 rounded-lg' in MODAL


def test_uses_layout_effect_for_autoscroll():
    assert "useLayoutEffect" in DETAIL
    assert "useLayoutEffect" in MODAL


def test_parser_memoised():
    assert "useMemo" in ANSI_TEXT
