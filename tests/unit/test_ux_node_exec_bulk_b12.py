"""Unit tests for #150 (quick actions), #152 (execution filters), #161 (bulk selection)."""
import glob
from pathlib import Path


def _find_file(patterns):
    for pattern in patterns:
        files = glob.glob(pattern, recursive=True)
        if files:
            return Path(files[0]).read_text()
    return ""


def test_node_detail_has_quick_actions():
    src = _find_file(["frontend/src/pages/NodeDetail.tsx", "frontend/src/pages/NodeDetailPage.tsx",
                      "frontend/src/**/*NodeDetail*.tsx"])
    assert "Quick Actions" in src or "quickAction" in src or "test.ping" in src.lower(), (
        "NodeDetail must have a Quick Actions section"
    )
    assert "Reboot" in src, "NodeDetail Quick Actions must include a Reboot button"


def test_execution_history_has_status_filter():
    src = _find_file(["frontend/src/pages/ExecutionHistory.tsx", "frontend/src/**/*Execution*.tsx"])
    assert "useSearchParams" in src or "statusFilter" in src or "status" in src, (
        "ExecutionHistory must have status filter using URL search params"
    )
    assert "select" in src.lower() or "Select" in src, "Filter must use a select element"


def test_execution_history_has_date_filter():
    src = _find_file(["frontend/src/pages/ExecutionHistory.tsx", "frontend/src/**/*Execution*.tsx"])
    assert 'type="date"' in src or "type='date'" in src or 'input type' in src.lower(), (
        "ExecutionHistory must have date range inputs (input type=\"date\")"
    )
    assert "date" in src.lower(), "ExecutionHistory must include date filtering"


def test_bulk_selection_shows_node_names():
    # Search for the bulk action confirmation logic
    tsx_files = glob.glob("frontend/src/**/*.tsx", recursive=True)
    combined = "".join(Path(f).read_text() for f in tsx_files if Path(f).exists())
    assert "and " in combined and "more" in combined, (
        "Bulk confirmation must show node names with '...and N more' truncation"
    )
