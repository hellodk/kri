"""Behavioral tests for #55: license compliance dashboard.

Replaces source-scrape checks against ``sbom.py`` with assertions on the real
copyleft license set, the real registered route, and the real aggregation
behaviour of the ``license_summary`` endpoint (mocked async DB). Frontend
wiring checks stay source-contract (frontend-owned ``.tsx``).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from fleet_platform.api.routes.sbom import _COPYLEFT_LICENSES, license_summary, router


def _route_for(endpoint) -> object:
    for r in router.routes:
        if getattr(r, "endpoint", None) is endpoint:
            return r
    raise AssertionError(f"No route registered for {endpoint!r}")


# ---------------------------------------------------------------------------
# Copyleft license set — real object membership
# ---------------------------------------------------------------------------


def test_copyleft_license_set_defined():
    assert isinstance(_COPYLEFT_LICENSES, frozenset)
    assert len(_COPYLEFT_LICENSES) > 0


def test_agpl_in_copyleft():
    assert "AGPL-3.0" in _COPYLEFT_LICENSES


def test_gpl_in_copyleft():
    assert "GPL-3.0" in _COPYLEFT_LICENSES


def test_permissive_license_not_in_copyleft():
    assert "MIT" not in _COPYLEFT_LICENSES
    assert "Apache-2.0" not in _COPYLEFT_LICENSES


# ---------------------------------------------------------------------------
# Route contract
# ---------------------------------------------------------------------------


def test_license_summary_endpoint_registered():
    route = _route_for(license_summary)
    assert route.path == "/api/v1/sbom/licenses/summary"


# ---------------------------------------------------------------------------
# Aggregation behaviour
# ---------------------------------------------------------------------------


def _summary_db(rows: list[tuple]) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_license_summary_counts_copyleft_deduplicated():
    import uuid

    n1, n2, n3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # (name, version, purl, licenses, node_id)
    rows = [
        ("foo", "1.0", "pkg:x/foo", ["GPL-3.0"], n1),
        ("bar", "2.0", "pkg:x/bar", ["MIT"], n2),
        ("foo", "1.0", "pkg:x/foo", ["GPL-3.0"], n3),  # dup (name, license)
        ("baz", "1.0", "pkg:x/baz", [], n1),  # unknown license
    ]
    db = _summary_db(rows)

    result = await license_summary(db=db, _={})

    # foo/GPL-3.0 counted once despite appearing on two nodes.
    assert result["copyleft_count"] == 1
    assert result["unknown_license_count"] == 1


@pytest.mark.asyncio
async def test_license_summary_returns_top_licenses():
    import uuid

    n1 = uuid.uuid4()
    rows = [
        ("a", "1", "pkg:x/a", ["MIT"], n1),
        ("b", "1", "pkg:x/b", ["MIT"], n1),
        ("c", "1", "pkg:x/c", ["GPL-3.0"], n1),
    ]
    db = _summary_db(rows)

    result = await license_summary(db=db, _={})

    assert "top_licenses" in result
    top = {item["license"]: item["count"] for item in result["top_licenses"]}
    assert top["MIT"] == 2
    assert top["GPL-3.0"] == 1
    # MIT (most common) must rank first.
    assert result["top_licenses"][0]["license"] == "MIT"


@pytest.mark.asyncio
async def test_license_summary_empty_fleet():
    db = _summary_db([])
    result = await license_summary(db=db, _={})
    assert result["copyleft_count"] == 0
    assert result["top_licenses"] == []
    assert result["total_distinct_licenses"] == 0


# ---------------------------------------------------------------------------
# Frontend wiring — source-contract checks (frontend-owned .tsx).
# ---------------------------------------------------------------------------


def test_license_page_in_frontend():
    page = (Path(__file__).parent.parent.parent / "frontend/src/pages/LicensePage.tsx").read_text()
    assert "copyleft" in page.lower() or "LicensePage" in page


def test_license_reachable_from_sidebar():
    sidebar = (Path(__file__).parent.parent.parent / "frontend/src/components/Layout/Sidebar.tsx").read_text()
    assert "/compliance" in sidebar.lower() or "compliance" in sidebar.lower(), (
        "Sidebar must include /compliance which hosts the License compliance tab"
    )


def test_license_route_in_app():
    app = (Path(__file__).parent.parent.parent / "frontend/src/App.tsx").read_text()
    assert "license" in app.lower() or "LicensePage" in app
