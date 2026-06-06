"""Unit tests for SaltMasterProbe — issue #517, epic #523.

All network I/O (socket, requests) is mocked.  No live salt-api or DB.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_master(**kwargs):
    """Build a SaltMaster-like SimpleNamespace without hitting the DB."""
    from types import SimpleNamespace

    defaults = dict(
        id=uuid.uuid4(),
        name="test-master",
        enabled=True,
        is_default=False,
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


_PROBE = "fleet_platform.services.salt_master_probe"
_DNS_PATCH = f"{_PROBE}.socket.getaddrinfo"
_TCP_PATCH = f"{_PROBE}.socket.create_connection"
_POST_PATCH = f"{_PROBE}.requests.post"
_DNS_RV = [("", "", "", "", ("1.2.3.4", 0))]


def _ok_resp(data: dict | list) -> MagicMock:
    """Build a requests.Response mock that returns data as JSON with status 200."""
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = data
    r.raise_for_status = MagicMock()
    return r


def _error_resp(status_code: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    r.json.return_value = {}
    return r


# ---------------------------------------------------------------------------
# SaltMasterProbe — check_dns
# ---------------------------------------------------------------------------


class TestCheckDns:
    def test_dns_pass_on_resolved(self):
        from fleet_platform.services.salt_master_probe import _check_dns

        with patch(_DNS_PATCH, return_value=_DNS_RV):
            result = _check_dns("salt.test.local")

        assert result["check"] == "dns"
        assert result["status"] == "pass"

    def test_dns_fail_on_gaierror(self):
        import socket

        from fleet_platform.services.salt_master_probe import _check_dns

        with patch(
            "fleet_platform.services.salt_master_probe.socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            result = _check_dns("nonexistent.salt.local")

        assert result["check"] == "dns"
        assert result["status"] == "fail"
        assert "DNS resolution failed" in result["detail"]

    def test_dns_includes_latency(self):
        from fleet_platform.services.salt_master_probe import _check_dns

        with patch("fleet_platform.services.salt_master_probe.socket.getaddrinfo", return_value=[]):
            result = _check_dns("salt.test.local")

        assert isinstance(result["latency_ms"], int)
        assert result["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# SaltMasterProbe — check_tcp
# ---------------------------------------------------------------------------


class TestCheckTcp:
    def test_tcp_pass_on_connection(self):
        from fleet_platform.services.salt_master_probe import _check_tcp

        mock_socket = MagicMock()
        mock_socket.__enter__ = MagicMock(return_value=mock_socket)
        mock_socket.__exit__ = MagicMock(return_value=False)

        with patch("fleet_platform.services.salt_master_probe.socket.create_connection", return_value=mock_socket):
            result = _check_tcp("salt.test.local", 4505, "tcp_4505")

        assert result["check"] == "tcp_4505"
        assert result["status"] == "pass"

    def test_tcp_fail_on_refused(self):
        from fleet_platform.services.salt_master_probe import _check_tcp

        with patch(
            "fleet_platform.services.salt_master_probe.socket.create_connection",
            side_effect=ConnectionRefusedError("Connection refused"),
        ):
            result = _check_tcp("salt.test.local", 4505, "tcp_4505")

        assert result["check"] == "tcp_4505"
        assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# SaltMasterProbe — salt_api_auth check
# ---------------------------------------------------------------------------


class TestSaltApiAuth:
    def test_auth_pass_on_200(self):
        from fleet_platform.services.salt_master_probe import _check_salt_api_auth

        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_ok_resp({"return": [{}]})):
            result = _check_salt_api_auth("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "salt_api_auth"
        assert result["status"] == "pass"

    def test_auth_fail_on_401(self):
        from fleet_platform.services.salt_master_probe import _check_salt_api_auth

        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_error_resp(401)):
            result = _check_salt_api_auth("http://salt.test:8080", "admin", "wrongpass", "pam")

        assert result["check"] == "salt_api_auth"
        assert result["status"] == "fail"
        assert "401" in result["detail"]

    def test_auth_fail_on_403(self):
        from fleet_platform.services.salt_master_probe import _check_salt_api_auth

        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_error_resp(403)):
            result = _check_salt_api_auth("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "salt_api_auth"
        assert result["status"] == "fail"
        assert "403" in result["detail"]

    def test_auth_fail_on_connection_error(self):
        import requests as req_lib

        from fleet_platform.services.salt_master_probe import _check_salt_api_auth

        with patch(
            "fleet_platform.services.salt_master_probe.requests.post",
            side_effect=req_lib.ConnectionError("Connection refused"),
        ):
            result = _check_salt_api_auth("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "salt_api_auth"
        assert result["status"] == "fail"

    def test_auth_does_not_raise(self):
        """Any exception must be caught — not propagated."""
        from fleet_platform.services.salt_master_probe import _check_salt_api_auth

        with patch(
            "fleet_platform.services.salt_master_probe.requests.post",
            side_effect=RuntimeError("unexpected"),
        ):
            result = _check_salt_api_auth("http://salt.test:8080", "admin", "pass", "pam")

        assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# SaltMasterProbe — key_store check
# ---------------------------------------------------------------------------


class TestKeyStore:
    def test_key_store_pass_on_readable_keys(self):
        from fleet_platform.services.salt_master_probe import _check_key_store

        keys_data = {"return": [{"minions": ["m1", "m2"], "minions_pre": []}]}
        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_ok_resp(keys_data)):
            result = _check_key_store("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "key_store"
        assert result["status"] == "pass"

    def test_key_store_pass_on_empty_but_readable(self):
        """Empty keystore is different from a permission error — must be pass."""
        from fleet_platform.services.salt_master_probe import _check_key_store

        keys_data = {"return": [{"minions": [], "minions_pre": []}]}
        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_ok_resp(keys_data)):
            result = _check_key_store("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "key_store"
        assert result["status"] == "pass"
        assert "permission" not in result["detail"].lower()

    def test_key_store_fail_on_401(self):
        """HTTP 401 from key.list_all → cannot read keys (permission)."""
        from fleet_platform.services.salt_master_probe import _check_key_store

        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_error_resp(401)):
            result = _check_key_store("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "key_store"
        assert result["status"] == "fail"
        assert "cannot read keys (permission)" in result["detail"]

    def test_key_store_fail_on_403(self):
        """HTTP 403 from key.list_all → cannot read keys (permission)."""
        from fleet_platform.services.salt_master_probe import _check_key_store

        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_error_resp(403)):
            result = _check_key_store("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "key_store"
        assert result["status"] == "fail"
        assert "cannot read keys (permission)" in result["detail"]

    def test_key_store_fail_on_permission_string_in_return(self):
        """Salt returns a string like 'Permission denied' in the return list → fail with (permission)."""
        from fleet_platform.services.salt_master_probe import _check_key_store

        perm_error_data = {"return": ["Permission denied: cannot read key dir"]}
        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_ok_resp(perm_error_data)):
            result = _check_key_store("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "key_store"
        assert result["status"] == "fail"
        assert "cannot read keys (permission)" in result["detail"]

    def test_key_store_fail_distinct_from_empty(self):
        """
        The detail string for empty-but-readable must NOT contain 'permission'.
        The detail for permission error MUST contain 'cannot read keys (permission)'.
        These are distinct outcomes.
        """
        from fleet_platform.services.salt_master_probe import _check_key_store

        # Empty keystore
        empty_data = {"return": [{"minions": []}]}
        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_ok_resp(empty_data)):
            empty_result = _check_key_store("http://salt.test:8080", "admin", "pass", "pam")

        # Permission error
        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_error_resp(403)):
            perm_result = _check_key_store("http://salt.test:8080", "admin", "pass", "pam")

        assert empty_result["status"] == "pass"
        assert perm_result["status"] == "fail"
        assert "cannot read keys (permission)" in perm_result["detail"]
        assert "cannot read keys (permission)" not in empty_result["detail"]

    def test_key_store_does_not_raise(self):
        from fleet_platform.services.salt_master_probe import _check_key_store

        with patch(
            "fleet_platform.services.salt_master_probe.requests.post",
            side_effect=RuntimeError("boom"),
        ):
            result = _check_key_store("http://salt.test:8080", "admin", "pass", "pam")

        assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# SaltMasterProbe — version check
# ---------------------------------------------------------------------------


class TestVersionCheck:
    def test_version_pass_on_ok_result(self):
        from fleet_platform.services.salt_master_probe import _check_version

        version_data = {"return": [{"up_to_date": True}]}
        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_ok_resp(version_data)):
            result = _check_version("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "version"
        assert result["status"] == "pass"

    def test_version_warn_on_mismatch(self):
        from fleet_platform.services.salt_master_probe import _check_version

        version_data = {"return": [{"up_to_date": False, "master": "3006.0", "minions": {"m1": "3005.0"}}]}
        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_ok_resp(version_data)):
            result = _check_version("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "version"
        assert result["status"] == "warn"

    def test_version_warn_on_error(self):
        """manage.versions unavailable → warn (not fail) — informational."""
        import requests as req_lib

        from fleet_platform.services.salt_master_probe import _check_version

        with patch(
            "fleet_platform.services.salt_master_probe.requests.post",
            side_effect=req_lib.ConnectionError("refused"),
        ):
            result = _check_version("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "version"
        assert result["status"] == "warn"


# ---------------------------------------------------------------------------
# SaltMasterProbe — minions_up check
# ---------------------------------------------------------------------------


class TestMinionsUp:
    def test_minions_up_pass_with_count(self):
        from fleet_platform.services.salt_master_probe import _check_minions_up

        up_data = {"return": [["m1", "m2", "m3"]]}
        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_ok_resp(up_data)):
            result = _check_minions_up("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "minions_up"
        assert result["status"] == "pass"
        assert "3" in result["detail"]

    def test_minions_up_pass_zero(self):
        from fleet_platform.services.salt_master_probe import _check_minions_up

        up_data = {"return": [[]]}
        with patch("fleet_platform.services.salt_master_probe.requests.post", return_value=_ok_resp(up_data)):
            result = _check_minions_up("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "minions_up"
        assert result["status"] == "pass"
        assert "0" in result["detail"]

    def test_minions_up_warn_on_error(self):
        """manage.up unavailable → warn — informational only."""
        import requests as req_lib

        from fleet_platform.services.salt_master_probe import _check_minions_up

        with patch(
            "fleet_platform.services.salt_master_probe.requests.post",
            side_effect=req_lib.ConnectionError("refused"),
        ):
            result = _check_minions_up("http://salt.test:8080", "admin", "pass", "pam")

        assert result["check"] == "minions_up"
        assert result["status"] == "warn"


# ---------------------------------------------------------------------------
# SaltMasterProbe — token_delivery check
# ---------------------------------------------------------------------------


class TestTokenDelivery:
    def test_token_delivery_pass_for_direct_mode(self):
        from fleet_platform.services.salt_master_probe import _check_token_delivery

        master = _make_master(token_delivery="direct")
        result = _check_token_delivery(master)
        assert result["check"] == "token_delivery"
        assert result["status"] == "pass"

    def test_token_delivery_pass_for_ingest_with_api_url(self):
        from fleet_platform.services.salt_master_probe import _check_token_delivery

        master = _make_master(token_delivery="ingest", api_url="http://salt.test:8080")
        result = _check_token_delivery(master)
        assert result["check"] == "token_delivery"
        assert result["status"] == "pass"

    def test_token_delivery_warn_for_ingest_without_api_url(self):
        from fleet_platform.services.salt_master_probe import _check_token_delivery

        master = _make_master(token_delivery="ingest", api_url=None)
        result = _check_token_delivery(master)
        assert result["check"] == "token_delivery"
        assert result["status"] == "warn"
        assert "api_url" in result["detail"]


# ---------------------------------------------------------------------------
# run_probe — aggregate logic
# ---------------------------------------------------------------------------


class TestRunProbeAggregate:
    @pytest.mark.asyncio
    async def test_all_pass_returns_healthy(self):
        """All checks pass → aggregate healthy."""

        from fleet_platform.services.salt_master_probe import run_probe

        master = _make_master(api_password_enc=None, token_delivery="direct")

        mock_socket = MagicMock()
        mock_socket.__enter__ = MagicMock(return_value=mock_socket)
        mock_socket.__exit__ = MagicMock(return_value=False)

        ok_resp = _ok_resp({"return": [{"up_to_date": True}]})
        keys_resp = _ok_resp({"return": [{"minions": ["m1"]}]})

        call_count = [0]

        def mock_post(url, **kwargs):
            call_count[0] += 1
            if "run" in url:
                c = call_count[0]
                if c == 1:
                    return ok_resp  # auth
                elif c == 2:
                    return keys_resp  # key_store
                elif c == 3:
                    return _ok_resp({"return": [{"up_to_date": True}]})  # version
                else:
                    return _ok_resp({"return": [["m1"]]})  # minions_up
            return ok_resp

        with (
            patch(_DNS_PATCH, return_value=_DNS_RV),
            patch(_TCP_PATCH, return_value=mock_socket),
            patch(_POST_PATCH, side_effect=mock_post),
        ):
            result = await run_probe(master)

        assert result["status"] == "healthy"
        assert isinstance(result["checks"], list)
        assert len(result["checks"]) > 0

    @pytest.mark.asyncio
    async def test_auth_fail_returns_unreachable(self):
        """When salt_api_auth fails → aggregate must be unreachable, no exception raised."""
        from fleet_platform.services.salt_master_probe import run_probe

        master = _make_master(api_password_enc=None, token_delivery="direct")

        mock_socket = MagicMock()
        mock_socket.__enter__ = MagicMock(return_value=mock_socket)
        mock_socket.__exit__ = MagicMock(return_value=False)

        with (
            patch(_DNS_PATCH, return_value=_DNS_RV),
            patch(_TCP_PATCH, return_value=mock_socket),
            patch(_POST_PATCH, return_value=_error_resp(401)),
        ):
            result = await run_probe(master)

        assert result["status"] == "unreachable"
        auth_checks = [c for c in result["checks"] if c["check"] == "salt_api_auth"]
        assert auth_checks, "salt_api_auth check must be present"
        assert auth_checks[0]["status"] == "fail"

    @pytest.mark.asyncio
    async def test_auth_fail_no_exception_raised(self):
        """run_probe must never raise regardless of network failures."""
        from fleet_platform.services.salt_master_probe import run_probe

        master = _make_master(api_password_enc=None)

        with (
            patch(
                "fleet_platform.services.salt_master_probe.socket.getaddrinfo",
                side_effect=Exception("unexpected"),
            ),
            patch(
                "fleet_platform.services.salt_master_probe.socket.create_connection",
                side_effect=Exception("unexpected"),
            ),
            patch(
                "fleet_platform.services.salt_master_probe.requests.post",
                side_effect=Exception("unexpected"),
            ),
        ):
            # Must not raise
            result = await run_probe(master)

        assert result["status"] in ("unreachable", "degraded", "healthy", "unknown")

    @pytest.mark.asyncio
    async def test_key_store_permission_fail_returns_degraded(self):
        """key_store fail (permission) with auth passing → degraded, not unreachable."""
        from fleet_platform.services.salt_master_probe import run_probe

        master = _make_master(api_password_enc=None, token_delivery="direct")

        mock_socket = MagicMock()
        mock_socket.__enter__ = MagicMock(return_value=mock_socket)
        mock_socket.__exit__ = MagicMock(return_value=False)

        call_count = [0]

        def mock_post(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # auth passes
                return _ok_resp({"return": [{}]})
            else:
                # key.list_all → 403
                return _error_resp(403)

        with (
            patch(_DNS_PATCH, return_value=_DNS_RV),
            patch(_TCP_PATCH, return_value=mock_socket),
            patch(_POST_PATCH, side_effect=mock_post),
        ):
            result = await run_probe(master)

        key_checks = [c for c in result["checks"] if c["check"] == "key_store"]
        assert key_checks, "key_store check must be present"
        assert key_checks[0]["status"] == "fail"
        assert "cannot read keys (permission)" in key_checks[0]["detail"]
        # Aggregate should be degraded since auth passed but key_store failed
        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_key_store_permission_distinct_from_empty(self):
        """Empty keystore check must be pass; permission-denied check must be fail."""
        from fleet_platform.services.salt_master_probe import run_probe

        master = _make_master(api_password_enc=None, token_delivery="direct")

        mock_socket = MagicMock()
        mock_socket.__enter__ = MagicMock(return_value=mock_socket)
        mock_socket.__exit__ = MagicMock(return_value=False)

        call_count_a = [0]

        def mock_post_empty(url, **kwargs):
            call_count_a[0] += 1
            if call_count_a[0] == 1:
                return _ok_resp({"return": [{}]})  # auth
            elif call_count_a[0] == 2:
                return _ok_resp({"return": [{"minions": [], "minions_pre": []}]})  # key_store empty
            else:
                return _ok_resp({"return": [{"up_to_date": True}]})  # other runners

        with (
            patch(_DNS_PATCH, return_value=_DNS_RV),
            patch(_TCP_PATCH, return_value=mock_socket),
            patch(_POST_PATCH, side_effect=mock_post_empty),
        ):
            result_empty = await run_probe(master)

        key_empty = [c for c in result_empty["checks"] if c["check"] == "key_store"][0]
        assert key_empty["status"] == "pass", "Empty keystore should be pass"
        assert "cannot read keys (permission)" not in key_empty["detail"]


# ---------------------------------------------------------------------------
# route — POST /api/v1/salt/masters/{id}/test — auth gates
# ---------------------------------------------------------------------------


class TestSaltMastersRoute:
    def test_route_requires_admin_role(self):
        """The route handler must declare require_role('admin') in its signature."""
        import inspect

        from fleet_platform.api.routes.salt_masters import test_salt_master

        src = inspect.getsource(test_salt_master)
        assert "require_role" in src, "test_salt_master must use require_role"
        assert "admin" in src, "test_salt_master must require admin role"

    @pytest.mark.asyncio
    async def test_route_404_for_unknown_id(self):
        """When no SaltMaster row is found → 404."""
        from fleet_platform.api.routes.salt_masters import test_salt_master

        admin_claims = {"sub": "admin1", "role": "admin"}
        unknown_id = uuid.uuid4()

        # Mock DB session: no master found
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await test_salt_master(master_id=unknown_id, db=mock_db, claims=admin_claims)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_route_returns_probe_result(self):
        """Happy path: master found → run_probe called → result returned."""
        from fleet_platform.api.routes.salt_masters import test_salt_master

        master = _make_master(api_password_enc=None, token_delivery="direct")
        admin_claims = {"sub": "admin1", "role": "admin"}

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = master
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        expected_probe = {
            "status": "healthy",
            "checks": [{"check": "dns", "status": "pass", "detail": "ok", "latency_ms": 1}],
        }

        with patch(
            "fleet_platform.api.routes.salt_masters.run_probe",
            new_callable=AsyncMock,
            return_value=expected_probe,
        ):
            result = await test_salt_master(master_id=master.id, db=mock_db, claims=admin_claims)

        assert result["status"] == "healthy"
        assert result["checks"][0]["check"] == "dns"

    @pytest.mark.asyncio
    async def test_route_persists_result_to_master(self):
        """After probing, status/checks/last_checked_at must be set on the master row."""
        from fleet_platform.api.routes.salt_masters import test_salt_master

        master = _make_master(api_password_enc=None, token_delivery="direct")
        admin_claims = {"sub": "admin1", "role": "admin"}

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = master
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        probe_resp = {
            "status": "degraded",
            "checks": [
                {"check": "dns", "status": "fail", "detail": "DNS failed", "latency_ms": 5},
            ],
        }

        with patch(
            "fleet_platform.api.routes.salt_masters.run_probe",
            new_callable=AsyncMock,
            return_value=probe_resp,
        ):
            await test_salt_master(master_id=master.id, db=mock_db, claims=admin_claims)

        assert master.status == "degraded"
        assert master.last_checked_at is not None
        assert master.last_error == "DNS failed"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_require_role_admin_denies_operator(self):
        """operator role must be denied on admin-only route (403)."""
        from fleet_platform.core.auth import require_role

        dep = require_role("admin")
        with pytest.raises(HTTPException) as exc_info:
            await dep(claims={"sub": "op1", "role": "operator"})
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_role_admin_denies_viewer(self):
        """viewer role must be denied on admin-only route (403)."""
        from fleet_platform.core.auth import require_role

        dep = require_role("admin")
        with pytest.raises(HTTPException) as exc_info:
            await dep(claims={"sub": "v1", "role": "viewer"})
        assert exc_info.value.status_code == 403
