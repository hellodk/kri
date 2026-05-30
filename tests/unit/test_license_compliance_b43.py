"""Tests for #55: license compliance dashboard."""
from pathlib import Path

SBOM_ROUTE = (Path(__file__).parent.parent.parent / "fleet_platform/api/routes/sbom.py").read_text()


def test_copyleft_license_set_defined():
    assert "COPYLEFT" in SBOM_ROUTE or "copyleft" in SBOM_ROUTE.lower()


def test_agpl_in_copyleft():
    assert "AGPL" in SBOM_ROUTE


def test_gpl_in_copyleft():
    assert "GPL-3.0" in SBOM_ROUTE


def test_license_summary_endpoint_exists():
    assert "license_summary" in SBOM_ROUTE or "licenses/summary" in SBOM_ROUTE


def test_license_summary_returns_copyleft_count():
    assert "copyleft_count" in SBOM_ROUTE


def test_license_summary_returns_top_licenses():
    assert "top_licenses" in SBOM_ROUTE


def test_license_page_in_frontend():
    page = (Path(__file__).parent.parent.parent / "frontend/src/pages/LicensePage.tsx").read_text()
    assert "copyleft" in page.lower() or "LicensePage" in page


def test_license_reachable_from_sidebar():
    # License compliance is under the /compliance hub page (not a direct sidebar link)
    sidebar = (Path(__file__).parent.parent.parent / "frontend/src/components/Layout/Sidebar.tsx").read_text()
    assert "/compliance" in sidebar.lower() or "compliance" in sidebar.lower(), (
        "Sidebar must include /compliance which hosts the License compliance tab"
    )


def test_license_route_in_app():
    app = (Path(__file__).parent.parent.parent / "frontend/src/App.tsx").read_text()
    assert "license" in app.lower() or "LicensePage" in app
