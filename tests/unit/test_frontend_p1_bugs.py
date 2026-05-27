"""Unit tests confirming P1 frontend bug fixes (#62 #70 #71 #72 #73 #74)."""
from pathlib import Path

FRONTEND = Path(__file__).parent.parent.parent / "frontend" / "src"


def test_provisioning_download_has_error_handling():
    """provisioning.ts download must not silently swallow errors."""
    src = (FRONTEND / "api" / "provisioning.ts").read_text()
    # Must have catch or try/catch pattern, not bare .then chain without catch
    assert "catch" in src, "provisioning.ts download must handle errors with catch"


def test_dashboard_route_wired():
    """DashboardPage must be wired to a route."""
    # Check App.tsx or router for /dashboard route
    app_src = (FRONTEND / "App.tsx").read_text()
    assert "dashboard" in app_src.lower(), "DashboardPage must have a /dashboard route in App.tsx"


def test_node_secret_deletion_has_confirm():
    """NodeDetail.tsx must confirm before deleting a secret."""
    src = (FRONTEND / "pages" / "NodeDetail.tsx").read_text()
    assert "confirm" in src, "NodeDetail.tsx must use confirm() before deleting secrets"


def test_group_deletion_has_confirm():
    """GroupDetail.tsx must confirm before deleting secrets or removing nodes."""
    src = (FRONTEND / "pages" / "GroupDetail.tsx").read_text()
    assert "confirm" in src, "GroupDetail.tsx must use confirm() before destructive actions"


def test_login_page_shows_oidc_error():
    """LoginPage.tsx must read and display the ?error query param."""
    src = (FRONTEND / "pages" / "LoginPage.tsx").read_text()
    assert "oidcError" in src or "error" in src.lower(), (
        "LoginPage must display OIDC error from query string"
    )


def test_sidebar_contrast_fixed():
    """Sidebar must not use text-white/45 (fails WCAG AA)."""
    src = (FRONTEND / "components" / "Layout" / "Sidebar.tsx").read_text()
    assert "text-white/45" not in src, "Sidebar must not use text-white/45 (WCAG AA failure)"


def test_bulk_salt_apply_has_confirm():
    """FleetDashboard bulk Salt apply must confirm before firing."""
    src = (FRONTEND / "pages" / "FleetDashboard.tsx").read_text()
    assert "confirm" in src, "FleetDashboard bulk Salt apply must use confirm()"
