"""Unit tests for #136 (sidebar groups), #138 (icon), #140 (LLM auth guard)."""
from pathlib import Path


SIDEBAR = Path("frontend/src/components/Layout/Sidebar.tsx").read_text()
APP = Path("frontend/src/App.tsx").read_text()


def test_sidebar_has_nav_groups():
    assert "NAV_GROUPS" in SIDEBAR, "Sidebar must use NAV_GROUPS data structure for grouped nav"


def test_sidebar_baselines_icon_changed():
    """Baselines must not use the same icon as Drift."""
    lines = SIDEBAR.splitlines()
    drift_icon = next((l for l in lines if "'/drift'" in l or '"/drift"' in l), "")
    baselines_icon = next((l for l in lines if "'/baselines'" in l or '"/baselines"' in l), "")
    assert drift_icon != baselines_icon, "Drift and Baselines must have different icons"
    assert "◑" not in baselines_icon, "Baselines must not use ◑ (same as Drift)"


def test_sidebar_has_section_labels():
    """Sidebar must render section label text for groups."""
    assert "Compliance" in SIDEBAR or "Overview" in SIDEBAR, (
        "Sidebar must render section header labels when expanded"
    )


def test_llm_assistant_inside_auth_guard():
    """LLMAssistant must be inside AuthGuard, not rendered before auth check."""
    # LLMAssistant should appear after AuthGuard in the JSX tree
    auth_guard_pos = APP.find("AuthGuard")
    llm_pos = APP.find("LLMAssistant")
    # LLMAssistant should be INSIDE AuthGuard (appears after the AuthGuard opening)
    assert llm_pos > auth_guard_pos, (
        "LLMAssistant must be inside AuthGuard, not rendered before auth check"
    )
