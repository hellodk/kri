# tests/unit/test_salt_keys_degraded.py
"""Tests for salt_keys degraded flag — updated for #518 salt-api adapter.

Previously tested PKI-filesystem PermissionError paths (#452).
Now tests the equivalent degraded semantics via salt-api (SaltApiError / no master).
The four core contract guarantees are preserved:
  - degraded=True when salt-api is unavailable
  - degraded=False on success
  - pending_count is always present
  - degraded buckets return [] not missing keys
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_ROUTE = "fleet_platform.api.routes.salt_keys"


def _make_master(**kwargs):
    from datetime import UTC, datetime

    defaults = dict(
        name="test-master",
        enabled=True,
        is_default=True,
        address="salt.test.local",
        api_url="http://salt.test.local:8080",
        api_user="saltadmin",
        api_password_enc=None,
        api_eauth="pam",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_db(master=None):
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.first.return_value = master
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_list_keys_returns_degraded_on_permission_error():
    """When SaltApiError (e.g. auth failure), degraded=True and degraded_reason is set."""
    from fleet_platform.api.routes.salt_keys import list_keys
    from fleet_platform.services.salt_api_client import SaltApiError

    master = _make_master()
    db = _make_db(master)

    with patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("salt-api authentication failed (401 Unauthorized)")):
        result = await list_keys(db=db, _={})

    assert result["degraded"] is True
    assert result["degraded_reason"] is not None
    assert len(result["degraded_reason"]) > 0


@pytest.mark.asyncio
async def test_list_keys_not_degraded_on_success():
    """Normal case: salt-api responds → degraded=False."""
    from fleet_platform.api.routes.salt_keys import list_keys

    master = _make_master()
    db = _make_db(master)

    with patch(
        f"{_ROUTE}.run_wheel",
        return_value={"minions": [], "minions_pre": [], "minions_rejected": [], "minions_denied": []},
    ):
        result = await list_keys(db=db, _={})

    assert result["degraded"] is False
    assert result["degraded_reason"] is None


@pytest.mark.asyncio
async def test_list_keys_pending_count_present():
    """pending_count must always be present."""
    from fleet_platform.api.routes.salt_keys import list_keys
    from fleet_platform.services.salt_api_client import SaltApiError

    master = _make_master()
    db = _make_db(master)

    with patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("connection refused")):
        result = await list_keys(db=db, _={})

    assert "pending_count" in result
    assert isinstance(result["pending_count"], int)


@pytest.mark.asyncio
async def test_list_keys_degraded_buckets_return_empty_list():
    """A degraded response returns [] for every bucket (no missing keys)."""
    from fleet_platform.api.routes.salt_keys import list_keys
    from fleet_platform.services.salt_api_client import SaltApiError

    master = _make_master()
    db = _make_db(master)

    with patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("timeout")):
        result = await list_keys(db=db, _={})

    assert "accepted" in result
    assert "pending" in result
    assert result["accepted"] == []
    assert result["pending"] == []
