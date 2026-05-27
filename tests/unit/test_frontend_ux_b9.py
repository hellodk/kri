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
    """LLMAssistant must be inside AuthGuard JSX, not rendered before auth check."""
    # Search within the component body only (skip import lines)
    jsx_start = APP.find("export default function App")
    assert jsx_start != -1, "App function not found"
    jsx = APP[jsx_start:]
    auth_guard_open = jsx.find("<AuthGuard")
    auth_guard_close = jsx.find("</AuthGuard>")
    llm_pos = jsx.find("<LLMAssistant")
    assert auth_guard_open != -1, "<AuthGuard not found in JSX"
    assert llm_pos != -1, "<LLMAssistant not found in JSX"
    assert auth_guard_open < llm_pos < auth_guard_close, (
        "LLMAssistant must appear between <AuthGuard> and </AuthGuard> tags"
    )
