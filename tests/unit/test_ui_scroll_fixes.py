"""TDD tests for UI scroll/sticky fixes (#363 #364 #365 #366).

These tests check that the specific CSS classes and patterns are present
in the frontend source files. They run fast (pure file reads, no DOM).
"""

import re

# ── #363 Sticky thead ──────────────────────────────────────────────────────────


def test_fleet_dashboard_thead_is_sticky():
    """Fleet dashboard <thead> must have sticky + z-index so headers stay visible (#363)."""
    content = open("frontend/src/pages/FleetDashboard.tsx").read()
    # Find the thead element and check it has sticky positioning
    thead_match = re.search(r"<thead([^>]*)>", content)
    assert thead_match, "<thead> not found in FleetDashboard.tsx"
    thead_attrs = thead_match.group(1)
    assert "sticky" in thead_attrs, "<thead> must have 'sticky' class — column headers scroll away without it (#363)"


def test_fleet_dashboard_th_has_opaque_background():
    """<th> cells need bg-white so row content doesn't bleed through sticky header (#363)."""
    content = open("frontend/src/pages/FleetDashboard.tsx").read()
    # After the thead, find the tr with th elements
    thead_section = content[content.find("<thead") :][:500]
    assert "bg-white" in thead_section or "bg-gray" in thead_section, (
        "Sticky <thead> requires an opaque background on header cells or the row (#363)"
    )


# ── #364 Sticky NodeDetail tab bar ────────────────────────────────────────────


def test_node_detail_tab_bar_is_sticky():
    """NodeDetail tab bar must be sticky so tabs remain accessible while scrolling (#364)."""
    content = open("frontend/src/pages/NodeDetail.tsx").read()
    # Find the tab bar div (has 'border-b border-gray-200 flex gap-1')
    tab_bar_match = re.search(r"<div[^>]*(?:border-b|flex gap-1)[^>]*>.*?{tabs\.map", content, re.DOTALL)
    assert tab_bar_match, "Tab bar div not found in NodeDetail.tsx"
    tab_bar_html = tab_bar_match.group(0)
    assert "sticky" in tab_bar_html, "Tab bar div must have 'sticky' class (#364)"


# ── #365 PlaybookJobDetail full-height log ────────────────────────────────────


def test_playbook_job_detail_log_no_max_height():
    """Log <pre> must NOT use maxHeight:70vh — causes double-scroll (#365)."""
    content = open("frontend/src/pages/PlaybookJobDetail.tsx").read()
    assert "maxHeight" not in content, (
        "Log panel must not use maxHeight inline style — causes double scroll (#365). Use flex-1 overflow-auto instead."
    )


def test_playbook_job_detail_page_uses_flex_layout():
    """Page wrapper should use flex layout so log fills remaining height (#365)."""
    content = open("frontend/src/pages/PlaybookJobDetail.tsx").read()
    # Should have a flex flex-col container and the log should be flex-1
    assert "flex-col" in content, "PlaybookJobDetail wrapper must use flex-col layout (#365)"


# ── #366 Collapsible secondary filters ────────────────────────────────────────


def test_fleet_dashboard_has_filter_toggle():
    """Fleet dashboard must have a toggle button for secondary filters (#366)."""
    content = open("frontend/src/pages/FleetDashboard.tsx").read()
    has_toggle = (
        "showMoreFilters" in content
        or "moreFilters" in content
        or "More filters" in content
        or "expandFilters" in content
    )
    assert has_toggle, "FleetDashboard must have a secondary-filters toggle to reduce visual clutter (#366)"


def test_fleet_dashboard_filter_count_badge():
    """Active secondary filter count must be shown on the toggle button (#366)."""
    content = open("frontend/src/pages/FleetDashboard.tsx").read()
    # Should compute and display count of active secondary filters
    has_count = (
        "activeFilterCount" in content
        or "secondaryFilterCount" in content
        or "filterCount" in content
        or re.search(r"filter.*count|count.*filter", content, re.I) is not None
    )
    assert has_count, "Toggle button must show count of active secondary filters (#366)"
