"""Source-contract tests for #370: LogPane + tailLines integration.

Verifies that:
- tailLines helper exports correctly
- LogPane imports and uses tailLines
- LogPane UI renders the indicator bar and toggle
- Scroll logic (isAtBottom, Jump to bottom) remains untouched
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
TAIL_LINES_FILE = ROOT / "frontend/src/lib/tailLines.ts"
LOG_PANE_FILE = ROOT / "frontend/src/lib/LogPane.tsx"


def test_tail_lines_exists():
    assert TAIL_LINES_FILE.exists(), "frontend/src/lib/tailLines.ts must exist"


def test_tail_lines_exports():
    content = TAIL_LINES_FILE.read_text()
    assert "export function tailLines" in content, "tailLines function must be exported"
    assert "TAIL_MAX_LINES = 500" in content, "TAIL_MAX_LINES constant must be 500"


def test_logpane_imports_tail_lines():
    content = LOG_PANE_FILE.read_text()
    assert "tailLines" in content, "LogPane must import/use tailLines"
    assert "TAIL_MAX_LINES" in content, "LogPane must reference TAIL_MAX_LINES"


def test_logpane_renders_indicator():
    content = LOG_PANE_FILE.read_text()
    assert "Showing last" in content, "LogPane must render the 'Showing last' indicator"
    assert "Show all" in content, "LogPane must render the 'Show all' toggle button"


def test_logpane_scroll_logic_untouched():
    content = LOG_PANE_FILE.read_text()
    assert "isAtBottom" in content, "LogPane must still use isAtBottom for scroll follow"
    assert "Jump to bottom" in content, "LogPane must still have the 'Jump to bottom' button"
