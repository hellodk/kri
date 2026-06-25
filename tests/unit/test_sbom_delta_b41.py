"""Behavioral tests for #167: SBOM delta endpoint.

Replaces source-scrape checks against ``sbom.py`` with assertions on the real
registered route, the real response schema, and the real delta-computation
behaviour (driven through a mocked async DB session). The single frontend
check stays a source-contract test (frontend-owned ``.ts``).
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from fleet_platform.api.routes.sbom import router, sbom_delta
from fleet_platform.schemas.sbom import SBOMDeltaResponse


def _route_for(endpoint) -> object:
    for r in router.routes:
        if getattr(r, "endpoint", None) is endpoint:
            return r
    raise AssertionError(f"No route registered for {endpoint!r}")


# ---------------------------------------------------------------------------
# Route + schema contract (real objects, not source text)
# ---------------------------------------------------------------------------


def test_sbom_delta_endpoint_registered():
    route = _route_for(sbom_delta)
    assert route is not None


def test_sbom_delta_endpoint_path():
    route = _route_for(sbom_delta)
    assert route.path == "/api/v1/sbom/delta/{node_id}"


def test_sbom_delta_response_has_new_and_removed_packages():
    fields = SBOMDeltaResponse.model_fields
    assert "new_packages" in fields
    assert "removed_packages" in fields
    assert "has_delta" in fields


# ---------------------------------------------------------------------------
# Delta computation behaviour
# ---------------------------------------------------------------------------


def _scan(scan_id: uuid.UUID, when: datetime) -> MagicMock:
    s = MagicMock()
    s.id = scan_id
    s.scanned_at = when
    return s


def _components_result(rows: list[tuple]) -> MagicMock:
    res = MagicMock()
    res.all.return_value = rows
    return res


def _scans_result(scans: list) -> MagicMock:
    res = MagicMock()
    res.scalars.return_value.all.return_value = scans
    return res


@pytest.mark.asyncio
async def test_sbom_delta_handles_insufficient_scans():
    node_id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scans_result([_scan(uuid.uuid4(), datetime.now(UTC))]))

    resp = await sbom_delta(node_id, db=db, _={})
    assert resp.has_delta is False
    assert resp.new_packages == []
    assert resp.removed_packages == []
    assert resp.message and "2 scans" in resp.message


@pytest.mark.asyncio
async def test_sbom_delta_computes_added_and_removed():
    node_id = uuid.uuid4()
    latest = _scan(uuid.uuid4(), datetime(2026, 2, 1, tzinfo=UTC))
    previous = _scan(uuid.uuid4(), datetime(2026, 1, 1, tzinfo=UTC))

    # (name, version, purl) tuples per scan.
    latest_rows = [
        ("libfoo", "2.0", "pkg:deb/libfoo@2.0"),  # version bump → new key
        ("shared", "1.0", "pkg:deb/shared@1.0"),  # unchanged
    ]
    prev_rows = [
        ("libfoo", "1.0", "pkg:deb/libfoo@1.0"),  # old version → removed key
        ("shared", "1.0", "pkg:deb/shared@1.0"),  # unchanged
        ("oldpkg", "0.1", "pkg:deb/oldpkg@0.1"),  # removed entirely
    ]

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scans_result([latest, previous]),
            _components_result(latest_rows),
            _components_result(prev_rows),
        ]
    )

    resp = await sbom_delta(node_id, db=db, _={})

    assert resp.has_delta is True
    new_purls = {p.purl for p in resp.new_packages}
    removed_purls = {p.purl for p in resp.removed_packages}
    assert new_purls == {"pkg:deb/libfoo@2.0"}
    assert removed_purls == {"pkg:deb/libfoo@1.0", "pkg:deb/oldpkg@0.1"}
    assert resp.new_count == 1
    assert resp.removed_count == 2


@pytest.mark.asyncio
async def test_sbom_delta_keys_on_purl_not_name():
    """A package whose purl is unchanged must not appear as added/removed even
    if other attributes differ — proving identity is keyed on purl."""
    node_id = uuid.uuid4()
    latest = _scan(uuid.uuid4(), datetime(2026, 2, 1, tzinfo=UTC))
    previous = _scan(uuid.uuid4(), datetime(2026, 1, 1, tzinfo=UTC))

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scans_result([latest, previous]),
            _components_result([("renamed", "1.0", "pkg:deb/stable@1.0")]),
            _components_result([("original", "1.0", "pkg:deb/stable@1.0")]),
        ]
    )

    resp = await sbom_delta(node_id, db=db, _={})
    assert resp.new_count == 0
    assert resp.removed_count == 0


@pytest.mark.asyncio
async def test_sbom_delta_only_reads_two_scans():
    """The scans query must be limited to the two most recent scans."""
    node_id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scans_result([]))

    await sbom_delta(node_id, db=db, _={})

    stmt = db.execute.call_args_list[0].args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "LIMIT 2" in compiled.upper()


# ---------------------------------------------------------------------------
# Frontend wiring — source-contract check (frontend-owned .ts).
# ---------------------------------------------------------------------------


def test_sbom_delta_in_frontend():
    api_files = list((Path(__file__).parent.parent.parent / "frontend/src/api").glob("sbom*.ts"))
    assert api_files, "No sbom API file found in frontend/src/api/"
    content = api_files[0].read_text()
    assert "getDelta" in content or "delta" in content.lower()
