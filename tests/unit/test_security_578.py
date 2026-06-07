"""Unit tests for security fixes introduced in issue #578.

Covers:
- webssh get_current_user_ws: fail-closed when revocation check raises
- salt_ops: reject invalid state names and invalid minion IDs
- platform_settings_svc: require distinct FERNET_SECRET_KEY in non-dev
- nodes GET routes: require viewer role (RBAC)
- security integration-status: SSRF guard rejects internal/loopback URLs
"""

import pytest

# ---------------------------------------------------------------------------
# 1. WebSSH — revocation check error must FAIL CLOSED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_auth_fail_closed_on_revocation_error():
    """get_current_user_ws raises ValueError when is_token_revoked raises a non-ValueError."""
    import unittest.mock as mock

    # Build a valid-looking token so decode_token succeeds
    from fleet_platform.core.auth import create_access_token

    token = create_access_token("00000000-0000-0000-0000-000000000001", "test@x.com", "viewer")

    # Patch is_token_revoked to simulate Redis connection error
    with mock.patch(
        "fleet_platform.api.routes.webssh.is_token_revoked",
        side_effect=ConnectionError("redis unavailable"),
    ):
        from fleet_platform.api.routes.webssh import get_current_user_ws

        fake_redis = mock.AsyncMock()
        with pytest.raises(ValueError, match="revocation check unavailable"):
            await get_current_user_ws(token, redis=fake_redis)


@pytest.mark.asyncio
async def test_ws_auth_passes_when_token_valid_and_not_revoked():
    """get_current_user_ws succeeds when token is valid and revocation check returns False."""
    import unittest.mock as mock

    from fleet_platform.core.auth import create_access_token

    token = create_access_token("00000000-0000-0000-0000-000000000001", "test@x.com", "viewer")

    with mock.patch(
        "fleet_platform.api.routes.webssh.is_token_revoked",
        return_value=False,
    ):
        from fleet_platform.api.routes.webssh import get_current_user_ws

        fake_redis = mock.AsyncMock()
        claims = await get_current_user_ws(token, redis=fake_redis)
        assert claims["email"] == "test@x.com"


@pytest.mark.asyncio
async def test_ws_auth_raises_when_token_revoked():
    """get_current_user_ws raises ValueError('Token has been revoked') when token is revoked."""
    import unittest.mock as mock

    from fleet_platform.core.auth import create_access_token

    token = create_access_token("00000000-0000-0000-0000-000000000001", "test@x.com", "viewer")

    with mock.patch(
        "fleet_platform.api.routes.webssh.is_token_revoked",
        return_value=True,
    ):
        from fleet_platform.api.routes.webssh import get_current_user_ws

        fake_redis = mock.AsyncMock()
        with pytest.raises(ValueError, match="revoked"):
            await get_current_user_ws(token, redis=fake_redis)


# ---------------------------------------------------------------------------
# 2. salt_ops — validate state name
# ---------------------------------------------------------------------------


def test_salt_ops_rejects_invalid_state_name_with_shell_chars():
    """_validate_state_name raises HTTPException for state names containing shell metacharacters."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.salt_ops import _validate_state_name

    with pytest.raises(HTTPException) as exc_info:
        _validate_state_name("jenkins; rm -rf /")
    assert exc_info.value.status_code == 422


def test_salt_ops_rejects_state_name_with_glob():
    """_validate_state_name raises HTTPException for state names containing wildcards."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.salt_ops import _validate_state_name

    with pytest.raises(HTTPException) as exc_info:
        _validate_state_name("*.sls")
    assert exc_info.value.status_code == 422


def test_salt_ops_rejects_state_name_with_path_traversal():
    """_validate_state_name raises HTTPException for path-traversal attempts."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.salt_ops import _validate_state_name

    with pytest.raises(HTTPException) as exc_info:
        _validate_state_name("../../etc/passwd")
    assert exc_info.value.status_code == 422


def test_salt_ops_accepts_valid_state_name():
    """_validate_state_name does not raise for a normal dotted state name."""
    from fleet_platform.api.routes.salt_ops import _validate_state_name

    # Should not raise
    _validate_state_name("jenkins_slave.init")
    _validate_state_name("base")
    _validate_state_name("some_state.sub.init")


# ---------------------------------------------------------------------------
# 3. salt_ops — validate minion IDs
# ---------------------------------------------------------------------------


def test_salt_ops_rejects_minion_id_with_glob():
    """_validate_minion_ids raises HTTPException for glob/wildcard minion IDs."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.salt_ops import _validate_minion_ids

    with pytest.raises(HTTPException) as exc_info:
        _validate_minion_ids(["*"])
    assert exc_info.value.status_code == 422


def test_salt_ops_rejects_minion_id_with_comma():
    """_validate_minion_ids raises HTTPException for minion IDs containing commas."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.salt_ops import _validate_minion_ids

    with pytest.raises(HTTPException) as exc_info:
        _validate_minion_ids(["mac-mini-1,mac-mini-2"])
    assert exc_info.value.status_code == 422


def test_salt_ops_rejects_minion_id_with_shell_chars():
    """_validate_minion_ids raises HTTPException for minion IDs with shell chars."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.salt_ops import _validate_minion_ids

    with pytest.raises(HTTPException) as exc_info:
        _validate_minion_ids(["mac$(id)"])
    assert exc_info.value.status_code == 422


def test_salt_ops_accepts_valid_minion_ids():
    """_validate_minion_ids does not raise for normal minion IDs."""
    from fleet_platform.api.routes.salt_ops import _validate_minion_ids

    # Should not raise
    _validate_minion_ids(["mac-mini-01", "mac.mini.02", "node_3"])


# ---------------------------------------------------------------------------
# 4. platform_settings_svc — FERNET_SECRET_KEY required in non-dev
# ---------------------------------------------------------------------------


def test_fernet_key_raises_in_non_dev_without_explicit_key(monkeypatch):
    """_fernet_key raises RuntimeError in non-development when FERNET_SECRET_KEY is absent."""

    import fleet_platform.core.config as cfg_mod
    import fleet_platform.services.platform_settings_svc as svc_mod

    monkeypatch.setattr(cfg_mod.settings, "environment", "production")
    monkeypatch.setattr(cfg_mod.settings, "fernet_secret_key", None)

    with pytest.raises(RuntimeError, match="FERNET_SECRET_KEY"):
        svc_mod._fernet_key()


def test_fernet_key_uses_explicit_key_in_any_env(monkeypatch):
    """_fernet_key uses FERNET_SECRET_KEY when set, regardless of environment."""
    from cryptography.fernet import Fernet

    import fleet_platform.core.config as cfg_mod
    import fleet_platform.services.platform_settings_svc as svc_mod

    good_key = Fernet.generate_key().decode()
    monkeypatch.setattr(cfg_mod.settings, "environment", "production")
    monkeypatch.setattr(cfg_mod.settings, "fernet_secret_key", good_key)

    key = svc_mod._fernet_key()
    assert key == good_key.encode()


def test_fernet_key_dev_fallback_warns(monkeypatch, caplog):
    """_fernet_key falls back to JWT-derived key in dev and emits a warning."""
    import logging

    import fleet_platform.core.config as cfg_mod
    import fleet_platform.services.platform_settings_svc as svc_mod

    monkeypatch.setattr(cfg_mod.settings, "environment", "development")
    monkeypatch.setattr(cfg_mod.settings, "fernet_secret_key", None)
    monkeypatch.setattr(cfg_mod.settings, "jwt_secret", "dev-secret-key-for-test-only")

    with caplog.at_level(logging.WARNING, logger="fleet_platform.services.platform_settings_svc"):
        key = svc_mod._fernet_key()

    assert key is not None
    assert any("FERNET_SECRET_KEY" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 5. nodes GET routes — require viewer role
# ---------------------------------------------------------------------------


def test_nodes_get_node_requires_viewer_role():
    """GET /nodes/{id} endpoint is guarded by require_role (not bare get_current_user)."""
    import inspect

    from fleet_platform.api.routes.nodes import get_node

    sig = inspect.signature(get_node)
    for param in sig.parameters.values():
        default = param.default
        # Check if the Depends uses require_role (not get_current_user directly)
        if hasattr(default, "dependency"):
            dep = default.dependency
            if hasattr(dep, "__name__") and dep.__name__ == "get_current_user":
                # Bare get_current_user is not acceptable — test fails
                pytest.fail(f"get_node param {param.name!r} uses bare get_current_user instead of require_role")


def test_nodes_get_facts_requires_viewer_role():
    """GET /nodes/{id}/facts endpoint is guarded by require_role (not bare get_current_user)."""
    import inspect

    from fleet_platform.api.routes.nodes import get_node_facts

    sig = inspect.signature(get_node_facts)
    for param in sig.parameters.values():
        default = param.default
        if hasattr(default, "dependency"):
            dep = default.dependency
            if hasattr(dep, "__name__") and dep.__name__ == "get_current_user":
                pytest.fail(f"get_node_facts param {param.name!r} uses bare get_current_user instead of require_role")


def test_nodes_get_packages_requires_viewer_role():
    """GET /nodes/{id}/packages endpoint is guarded by require_role (not bare get_current_user)."""
    import inspect

    from fleet_platform.api.routes.nodes import get_node_packages

    sig = inspect.signature(get_node_packages)
    for param in sig.parameters.values():
        default = param.default
        if hasattr(default, "dependency"):
            dep = default.dependency
            if hasattr(dep, "__name__") and dep.__name__ == "get_current_user":
                pytest.fail(
                    f"get_node_packages param {param.name!r} uses bare get_current_user instead of require_role"
                )


# ---------------------------------------------------------------------------
# 6. security integration-status — SSRF guard
# ---------------------------------------------------------------------------


def test_ssrf_guard_rejects_loopback():
    """_ssrf_safe_url raises HTTPException for loopback IP."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.security import _ssrf_safe_url

    with pytest.raises(HTTPException) as exc_info:
        _ssrf_safe_url("http://127.0.0.1:8080/api")
    assert exc_info.value.status_code == 422


def test_ssrf_guard_rejects_metadata_ip():
    """_ssrf_safe_url raises HTTPException for AWS metadata IP 169.254.169.254."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.security import _ssrf_safe_url

    with pytest.raises(HTTPException) as exc_info:
        _ssrf_safe_url("http://169.254.169.254/latest/meta-data/")
    assert exc_info.value.status_code == 422


def test_ssrf_guard_rejects_private_ip():
    """_ssrf_safe_url raises HTTPException for RFC-1918 private IP."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.security import _ssrf_safe_url

    with pytest.raises(HTTPException) as exc_info:
        _ssrf_safe_url("http://192.168.1.1/admin")
    assert exc_info.value.status_code == 422


def test_ssrf_guard_rejects_bad_scheme():
    """_ssrf_safe_url raises HTTPException for non-http/https schemes."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.security import _ssrf_safe_url

    with pytest.raises(HTTPException) as exc_info:
        _ssrf_safe_url("file:///etc/passwd")
    assert exc_info.value.status_code == 422

    with pytest.raises(HTTPException) as exc_info:
        _ssrf_safe_url("ftp://internal.host/")
    assert exc_info.value.status_code == 422


def test_ssrf_guard_allows_public_https_hostname():
    """_ssrf_safe_url does not raise for a normal public HTTPS hostname."""
    from fleet_platform.api.routes.security import _ssrf_safe_url

    # Should not raise
    _ssrf_safe_url("https://sonarqube.example.com")
    _ssrf_safe_url("http://cxone.example.com:8080")


def test_ssrf_guard_rejects_10_block():
    """_ssrf_safe_url raises HTTPException for 10.x.x.x private range."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.security import _ssrf_safe_url

    with pytest.raises(HTTPException) as exc_info:
        _ssrf_safe_url("https://10.0.0.1/api/health")
    assert exc_info.value.status_code == 422
