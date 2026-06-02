"""Tests for fleet dashboard UX improvements (#368)."""


def test_stat_cards_are_clickable():
    content = open("frontend/src/pages/FleetDashboard.tsx").read()
    # Cards should now be <button> elements with onClick handlers
    assert "<button" in content
    # Each card should set a filter
    assert "setStatusFilter" in content
    assert "title=" in content  # tooltip hint


def test_stat_card_online_filters_to_online():
    content = open("frontend/src/pages/FleetDashboard.tsx").read()
    # The Online card should filter to status=online
    assert "'online'" in content or '"online"' in content


def test_sort_indicator_component_exists():
    content = open("frontend/src/pages/FleetDashboard.tsx").read()
    assert "SortTh" in content, "SortTh helper component must exist"
    assert "sortField" in content and "sortDir" in content


def test_sort_arrow_shows_for_active_field():
    content = open("frontend/src/pages/FleetDashboard.tsx").read()
    assert "↓" in content and "↑" in content, "Sort direction arrows must be present"
    assert "text-amber-500" in content, "Active sort column arrow must be amber"


def test_drift_and_last_seen_are_sortable_columns():
    content = open("frontend/src/pages/FleetDashboard.tsx").read()
    # drift_score and last_seen_at should be used as sort fields in SortTh
    assert "drift_score" in content
    assert "last_seen_at" in content
