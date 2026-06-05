"""Unit tests for #151 — role hierarchy in require_role."""

import pytest
from fastapi import HTTPException


def _make_claims(role: str) -> dict:
    return {"sub": "user1", "role": role}


@pytest.mark.asyncio
async def test_viewer_can_access_viewer_endpoint():
    from fleet_platform.core.auth import require_role

    dep = require_role("viewer")
    claims = await dep(claims=_make_claims("viewer"))
    assert claims["role"] == "viewer"


@pytest.mark.asyncio
async def test_operator_can_access_viewer_endpoint():
    """operator must be allowed on viewer-minimum endpoints (hierarchy)."""
    from fleet_platform.core.auth import require_role

    dep = require_role("viewer")
    claims = await dep(claims=_make_claims("operator"))
    assert claims["role"] == "operator"


@pytest.mark.asyncio
async def test_admin_can_access_operator_endpoint():
    """admin must be allowed on operator-minimum endpoints."""
    from fleet_platform.core.auth import require_role

    dep = require_role("operator")
    claims = await dep(claims=_make_claims("admin"))
    assert claims["role"] == "admin"


@pytest.mark.asyncio
async def test_viewer_cannot_access_operator_endpoint():
    """viewer must be denied on operator-minimum endpoints."""
    from fleet_platform.core.auth import require_role

    dep = require_role("operator")
    with pytest.raises(HTTPException) as exc_info:
        await dep(claims=_make_claims("viewer"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_operator_cannot_access_admin_endpoint():
    """operator must be denied on admin-only endpoints."""
    from fleet_platform.core.auth import require_role

    dep = require_role("admin")
    with pytest.raises(HTTPException) as exc_info:
        await dep(claims=_make_claims("operator"))
    assert exc_info.value.status_code == 403
