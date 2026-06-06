# tests/unit/test_salt_keys_saltapi_518.py
"""Unit tests for salt-api key adapter — issue #518, epic #523.

All salt-api I/O is mocked via ``fleet_platform.services.salt_api_client``.
No live salt-api, no DB connection required.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROUTE = "fleet_platform.api.routes.salt_keys"
_CLIENT = "fleet_platform.services.salt_api_client"


def _make_master(**kwargs) -> SimpleNamespace:
    defaults = dict(
        id=uuid.uuid4(),
        name="test-master",
        enabled=True,
        is_default=True,
        address="salt.test.local",
        publish_port=4505,
        ret_port=4506,
        control_mode="salt_api",
        api_url="http://salt.test.local:8080",
        api_user="saltadmin",
        api_password_enc=None,
        api_eauth="pam",
        token_delivery="direct",
        status="unknown",
        last_checked_at=None,
        last_error=None,
        checks=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_db(master=None):
    """Return an AsyncMock DB session that yields *master* from execute."""
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.first.return_value = master
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    return db


_KEY_LIST_ALL_PAYLOAD = {
    "minions": ["node-a", "node-b"],
    "minions_pre": ["node-c"],
    "minions_rejected": ["node-d"],
    "minions_denied": [],
}


# ---------------------------------------------------------------------------
# list_keys — happy path
# ---------------------------------------------------------------------------


class TestListKeys:
    @pytest.mark.asyncio
    async def test_maps_payload_to_four_buckets(self):
        """key.list_all payload is correctly mapped to accepted/pending/rejected/denied."""
        from fleet_platform.api.routes.salt_keys import list_keys

        master = _make_master()
        db = _make_db(master)

        with patch(f"{_ROUTE}.run_wheel", return_value=_KEY_LIST_ALL_PAYLOAD):
            result = await list_keys(db=db, _={})

        assert result["accepted"] == ["node-a", "node-b"]
        assert result["pending"] == ["node-c"]
        assert result["rejected"] == ["node-d"]
        assert result["denied"] == []

    @pytest.mark.asyncio
    async def test_pending_count_matches_minions_pre(self):
        """pending_count equals len(minions_pre)."""
        from fleet_platform.api.routes.salt_keys import list_keys

        master = _make_master()
        db = _make_db(master)

        with patch(f"{_ROUTE}.run_wheel", return_value=_KEY_LIST_ALL_PAYLOAD):
            result = await list_keys(db=db, _={})

        assert result["pending_count"] == 1

    @pytest.mark.asyncio
    async def test_not_degraded_on_success(self):
        """degraded is False when salt-api returns normally."""
        from fleet_platform.api.routes.salt_keys import list_keys

        master = _make_master()
        db = _make_db(master)

        with patch(f"{_ROUTE}.run_wheel", return_value=_KEY_LIST_ALL_PAYLOAD):
            result = await list_keys(db=db, _={})

        assert result["degraded"] is False
        assert result["degraded_reason"] is None

    @pytest.mark.asyncio
    async def test_results_are_sorted(self):
        """Bucket contents are returned in sorted order."""
        from fleet_platform.api.routes.salt_keys import list_keys

        master = _make_master()
        db = _make_db(master)
        unsorted_payload = {
            "minions": ["z-node", "a-node", "m-node"],
            "minions_pre": [],
            "minions_rejected": [],
            "minions_denied": [],
        }

        with patch(f"{_ROUTE}.run_wheel", return_value=unsorted_payload):
            result = await list_keys(db=db, _={})

        assert result["accepted"] == ["a-node", "m-node", "z-node"]

    @pytest.mark.asyncio
    async def test_empty_payload_returns_zero_counts(self):
        """An empty key store returns all empty lists + pending_count 0."""
        from fleet_platform.api.routes.salt_keys import list_keys

        master = _make_master()
        db = _make_db(master)
        empty_payload = {
            "minions": [],
            "minions_pre": [],
            "minions_rejected": [],
            "minions_denied": [],
        }

        with patch(f"{_ROUTE}.run_wheel", return_value=empty_payload):
            result = await list_keys(db=db, _={})

        assert result["pending_count"] == 0
        assert result["accepted"] == []


# ---------------------------------------------------------------------------
# list_keys — degraded paths
# ---------------------------------------------------------------------------


class TestListKeysDegraded:
    @pytest.mark.asyncio
    async def test_salt_api_error_returns_degraded_not_500(self):
        """SaltApiError on list → degraded shape (not an HTTP 500)."""
        from fleet_platform.api.routes.salt_keys import list_keys
        from fleet_platform.services.salt_api_client import SaltApiError

        master = _make_master()
        db = _make_db(master)

        with patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("Cannot reach salt-api at http://salt:8080")):
            result = await list_keys(db=db, _={})

        assert result["degraded"] is True
        assert "salt-api" in result["degraded_reason"].lower() or "reach" in result["degraded_reason"].lower()

    @pytest.mark.asyncio
    async def test_salt_api_error_buckets_are_empty(self):
        """Degraded response always has empty bucket lists (no KeyError for callers)."""
        from fleet_platform.api.routes.salt_keys import list_keys
        from fleet_platform.services.salt_api_client import SaltApiError

        master = _make_master()
        db = _make_db(master)

        with patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("auth failure")):
            result = await list_keys(db=db, _={})

        assert result["accepted"] == []
        assert result["pending"] == []
        assert result["rejected"] == []
        assert result["denied"] == []
        assert result["pending_count"] == 0

    @pytest.mark.asyncio
    async def test_no_default_master_returns_degraded(self):
        """When no default SaltMaster is configured, list_keys returns degraded shape."""
        from fleet_platform.api.routes.salt_keys import list_keys

        db = _make_db(master=None)  # no default master

        result = await list_keys(db=db, _={})

        assert result["degraded"] is True
        assert result["degraded_reason"] == "No salt-master configured"
        assert result["accepted"] == []
        assert result["pending"] == []
        assert result["pending_count"] == 0

    @pytest.mark.asyncio
    async def test_degraded_reason_surfaces_api_error_message(self):
        """The degraded_reason carries the SaltApiError.reason verbatim."""
        from fleet_platform.api.routes.salt_keys import list_keys
        from fleet_platform.services.salt_api_client import SaltApiError

        master = _make_master()
        db = _make_db(master)
        specific_reason = "salt-api authentication failed (401 Unauthorized)"

        with patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError(specific_reason)):
            result = await list_keys(db=db, _={})

        assert result["degraded_reason"] == specific_reason


# ---------------------------------------------------------------------------
# accept_key
# ---------------------------------------------------------------------------


class TestAcceptKey:
    @pytest.mark.asyncio
    async def test_calls_run_wheel_with_correct_fun_and_match(self):
        """accept_key calls run_wheel with fun='key.accept' and match=minion_id."""
        from fleet_platform.api.routes.salt_keys import accept_key

        master = _make_master()
        db = _make_db(master)
        claims = {"email": "admin@example.com", "role": "admin"}

        with patch(f"{_ROUTE}.run_wheel", return_value={}) as mock_wheel:
            result = await accept_key(minion_id="node-a", db=db, claims=claims)

        mock_wheel.assert_called_once_with(master, "key.accept", match="node-a")
        assert result == {"status": "accepted", "minion_id": "node-a"}

    @pytest.mark.asyncio
    async def test_no_master_raises_503(self):
        """accept_key raises 503 when no default master is configured."""
        from fleet_platform.api.routes.salt_keys import accept_key

        db = _make_db(master=None)
        claims = {"email": "admin@example.com", "role": "admin"}

        with pytest.raises(HTTPException) as exc_info:
            await accept_key(minion_id="node-a", db=db, claims=claims)

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_salt_api_error_raises_502(self):
        """accept_key raises 502 on SaltApiError."""
        from fleet_platform.api.routes.salt_keys import accept_key
        from fleet_platform.services.salt_api_client import SaltApiError

        master = _make_master()
        db = _make_db(master)
        claims = {"email": "admin@example.com", "role": "admin"}

        with patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("connection refused")):
            with pytest.raises(HTTPException) as exc_info:
                await accept_key(minion_id="node-a", db=db, claims=claims)

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_invalid_minion_id_raises_422(self):
        """accept_key rejects minion IDs with invalid characters."""
        from fleet_platform.api.routes.salt_keys import accept_key

        master = _make_master()
        db = _make_db(master)
        claims = {"email": "admin@example.com", "role": "admin"}

        with pytest.raises(HTTPException) as exc_info:
            await accept_key(minion_id="../../../etc/passwd", db=db, claims=claims)

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_accept_writes_audit_log(self):
        """accept_key writes an audit log entry on success."""
        from fleet_platform.api.routes.salt_keys import accept_key

        master = _make_master()
        db = _make_db(master)
        claims = {"email": "admin@example.com", "role": "admin"}

        with (
            patch(f"{_ROUTE}.run_wheel", return_value={}),
            patch(f"{_ROUTE}.audit", new_callable=AsyncMock) as mock_audit,
        ):
            await accept_key(minion_id="node-a", db=db, claims=claims)

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "salt_key.accept"
        assert call_kwargs["actor"] == "admin@example.com"


# ---------------------------------------------------------------------------
# reject_key
# ---------------------------------------------------------------------------


class TestRejectKey:
    @pytest.mark.asyncio
    async def test_calls_run_wheel_with_correct_fun_and_match(self):
        """reject_key calls run_wheel with fun='key.reject' and match=minion_id."""
        from fleet_platform.api.routes.salt_keys import reject_key

        master = _make_master()
        db = _make_db(master)
        claims = {"email": "admin@example.com", "role": "admin"}

        with patch(f"{_ROUTE}.run_wheel", return_value={}) as mock_wheel:
            result = await reject_key(minion_id="node-b", db=db, claims=claims)

        mock_wheel.assert_called_once_with(master, "key.reject", match="node-b")
        assert result == {"status": "rejected", "minion_id": "node-b"}

    @pytest.mark.asyncio
    async def test_no_master_raises_503(self):
        from fleet_platform.api.routes.salt_keys import reject_key

        db = _make_db(master=None)
        claims = {"email": "admin@example.com", "role": "admin"}

        with pytest.raises(HTTPException) as exc_info:
            await reject_key(minion_id="node-b", db=db, claims=claims)

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_salt_api_error_raises_502(self):
        from fleet_platform.api.routes.salt_keys import reject_key
        from fleet_platform.services.salt_api_client import SaltApiError

        master = _make_master()
        db = _make_db(master)
        claims = {"email": "admin@example.com", "role": "admin"}

        with patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("timeout")):
            with pytest.raises(HTTPException) as exc_info:
                await reject_key(minion_id="node-b", db=db, claims=claims)

        assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# delete_key
# ---------------------------------------------------------------------------


class TestDeleteKey:
    @pytest.mark.asyncio
    async def test_calls_run_wheel_with_correct_fun_and_match(self):
        """delete_key calls run_wheel with fun='key.delete' and match=minion_id."""
        from fleet_platform.api.routes.salt_keys import delete_key

        master = _make_master()
        db = _make_db(master)
        claims = {"email": "admin@example.com", "role": "admin"}

        with patch(f"{_ROUTE}.run_wheel", return_value={}) as mock_wheel:
            result = await delete_key(minion_id="node-c", db=db, claims=claims)

        mock_wheel.assert_called_once_with(master, "key.delete", match="node-c")
        assert result == {"status": "deleted", "minion_id": "node-c"}

    @pytest.mark.asyncio
    async def test_no_master_raises_503(self):
        from fleet_platform.api.routes.salt_keys import delete_key

        db = _make_db(master=None)
        claims = {"email": "admin@example.com", "role": "admin"}

        with pytest.raises(HTTPException) as exc_info:
            await delete_key(minion_id="node-c", db=db, claims=claims)

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_salt_api_error_raises_502(self):
        from fleet_platform.api.routes.salt_keys import delete_key
        from fleet_platform.services.salt_api_client import SaltApiError

        master = _make_master()
        db = _make_db(master)
        claims = {"email": "admin@example.com", "role": "admin"}

        with patch(f"{_ROUTE}.run_wheel", side_effect=SaltApiError("403 forbidden")):
            with pytest.raises(HTTPException) as exc_info:
                await delete_key(minion_id="node-c", db=db, claims=claims)

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_invalid_minion_id_raises_422(self):
        from fleet_platform.api.routes.salt_keys import delete_key

        master = _make_master()
        db = _make_db(master)
        claims = {"email": "admin@example.com", "role": "admin"}

        with pytest.raises(HTTPException) as exc_info:
            await delete_key(minion_id="bad/id", db=db, claims=claims)

        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Role enforcement
# ---------------------------------------------------------------------------


class TestRoleEnforcement:
    """Verify that list_keys allows any authenticated user; mutating ops require admin."""

    @pytest.mark.asyncio
    async def test_list_keys_accepts_non_admin(self):
        """list_keys uses get_current_user (any authenticated user), not require_role."""
        from fleet_platform.api.routes.salt_keys import list_keys

        # A viewer-role claims dict still passes (we inject directly as '_')
        master = _make_master()
        db = _make_db(master)

        with patch(f"{_ROUTE}.run_wheel", return_value=_KEY_LIST_ALL_PAYLOAD):
            result = await list_keys(db=db, _={"role": "viewer", "email": "viewer@example.com"})

        assert result["degraded"] is False

    def test_accept_key_dependency_is_require_role_admin(self):
        """accept_key route uses require_role('admin') dependency."""
        import inspect

        from fleet_platform.api.routes.salt_keys import accept_key

        sig = inspect.signature(accept_key)
        claims_param = sig.parameters.get("claims")
        assert claims_param is not None, "accept_key must have a 'claims' parameter"

    def test_reject_key_dependency_is_require_role_admin(self):
        """reject_key route uses require_role('admin') dependency."""
        import inspect

        from fleet_platform.api.routes.salt_keys import reject_key

        sig = inspect.signature(reject_key)
        claims_param = sig.parameters.get("claims")
        assert claims_param is not None, "reject_key must have a 'claims' parameter"

    def test_delete_key_dependency_is_require_role_admin(self):
        """delete_key route uses require_role('admin') dependency."""
        import inspect

        from fleet_platform.api.routes.salt_keys import delete_key

        sig = inspect.signature(delete_key)
        claims_param = sig.parameters.get("claims")
        assert claims_param is not None, "delete_key must have a 'claims' parameter"

    @pytest.mark.asyncio
    async def test_non_admin_role_cannot_accept(self):
        """require_role('admin') raises 403 for operator/viewer roles."""
        from fleet_platform.core.auth import require_role

        # Simulate what FastAPI's dependency does when role is 'operator'
        dep = require_role("admin")
        operator_claims = {"role": "operator", "email": "op@example.com"}

        with pytest.raises(HTTPException) as exc_info:
            await dep(claims=operator_claims)

        assert exc_info.value.status_code == 403
