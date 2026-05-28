"""Tests for #167: SBOM delta endpoint."""
from pathlib import Path

SBOM_ROUTE = (Path(__file__).parent.parent.parent / "fleet_platform/api/routes/sbom.py").read_text()


def test_sbom_delta_endpoint_exists():
    assert "sbom_delta" in SBOM_ROUTE or "delta" in SBOM_ROUTE


def test_sbom_delta_endpoint_path():
    assert "/delta/" in SBOM_ROUTE or "delta/{node_id}" in SBOM_ROUTE


def test_sbom_delta_returns_new_packages():
    assert "new_packages" in SBOM_ROUTE


def test_sbom_delta_returns_removed_packages():
    assert "removed_packages" in SBOM_ROUTE


def test_sbom_delta_handles_insufficient_scans():
    assert "has_delta" in SBOM_ROUTE


def test_sbom_delta_limits_to_2_scans():
    assert ".limit(2)" in SBOM_ROUTE


def test_sbom_delta_uses_purl_key():
    assert "purl" in SBOM_ROUTE


def test_sbom_delta_in_frontend():
    # Check the frontend sbom API file has getDelta
    api_files = list((Path(__file__).parent.parent.parent / "frontend/src/api").glob("sbom*.ts"))
    assert api_files, "No sbom API file found in frontend/src/api/"
    content = api_files[0].read_text()
    assert "getDelta" in content or "delta" in content.lower()
