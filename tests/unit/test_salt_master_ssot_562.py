"""Unit tests for Salt Masters SSoT api_url derivation — issue #562.

Tests cover:
1. api_url derivation: use_tls=True → https, False → http; correct host:port.
2. Client-supplied api_url is ignored on create and update.
3. salt_tasks resolves credentials from DB, not SALT_API_* env vars.
4. Schema: control_mode / api_eauth / token_delivery / api_url absent from
   Create/Update inputs; api_url present (read-only) in Response.
5. Grep-guard: no runtime os.environ.get("SALT_API_*") in salt_tasks,
   and no runtime read of SALT_MASTER platform setting for address in
   ansible_tasks._get_bootstrap_settings.
"""

import uuid
from unittest.mock import MagicMock, patch

from fleet_platform.api.routes.salt_masters import _derive_api_url
from fleet_platform.schemas.salt_master import SaltMasterCreate, SaltMasterResponse, SaltMasterUpdate
from fleet_platform.workers import ansible_tasks, salt_tasks

# ---------------------------------------------------------------------------
# 1. api_url derivation function
# ---------------------------------------------------------------------------


class TestDeriveApiUrl:
    def test_use_tls_true_produces_https(self):
        result = _derive_api_url("salt.local", 8080, use_tls=True)
        assert result == "https://salt.local:8080"

    def test_use_tls_false_produces_http(self):
        result = _derive_api_url("salt.local", 8080, use_tls=False)
        assert result == "http://salt.local:8080"

    def test_custom_port(self):
        result = _derive_api_url("192.168.1.10", 9443, use_tls=True)
        assert result == "https://192.168.1.10:9443"

    def test_http_custom_port(self):
        result = _derive_api_url("192.168.1.10", 9090, use_tls=False)
        assert result == "http://192.168.1.10:9090"

    def test_default_port(self):
        result = _derive_api_url("master1.fleet", 8080, use_tls=False)
        assert result.startswith("http://master1.fleet:8080")

    def test_new_default_port_4507(self):
        """#690: 4507 is the new standard salt-api port (adjacent to ZMQ 4505/4506)."""
        result = _derive_api_url("master1.fleet", 4507, use_tls=True)
        assert result == "https://master1.fleet:4507"


# ---------------------------------------------------------------------------
# 2. Schema: inputs accepted / rejected
# ---------------------------------------------------------------------------


class TestSaltMasterCreateSchema:
    def test_has_salt_api_port_and_use_tls(self):
        schema = SaltMasterCreate(name="m1", address="salt.local", salt_api_port=8443, use_tls=True)
        assert schema.salt_api_port == 8443
        assert schema.use_tls is True

    def test_defaults(self):
        schema = SaltMasterCreate(name="m1", address="salt.local")
        assert schema.salt_api_port == 4507  # #690: changed from 8080
        assert schema.use_tls is True

    def test_control_mode_not_in_schema(self):
        """control_mode must not be an accepted input field (#562)."""
        fields = SaltMasterCreate.model_fields
        assert "control_mode" not in fields, "control_mode should not be in SaltMasterCreate"

    def test_api_eauth_not_in_schema(self):
        """api_eauth must not be an accepted input field (#562)."""
        fields = SaltMasterCreate.model_fields
        assert "api_eauth" not in fields, "api_eauth should not be in SaltMasterCreate"

    def test_token_delivery_not_in_schema(self):
        """token_delivery must not be an accepted input field (#562)."""
        fields = SaltMasterCreate.model_fields
        assert "token_delivery" not in fields, "token_delivery should not be in SaltMasterCreate"

    def test_api_url_not_in_create_schema(self):
        """api_url must not be an accepted input field — it is derived (#562)."""
        fields = SaltMasterCreate.model_fields
        assert "api_url" not in fields, "api_url should not be in SaltMasterCreate (it is derived)"

    def test_coerce_salt_api_port_returns_4507_for_none(self):
        """coerce_salt_api_port (on SaltMasterResponse) returns 4507 for None (#690).

        SaltMasterResponse.coerce_salt_api_port fires in mode='before' — it intercepts
        None from a pre-migration DB column and substitutes the new default 4507.
        """
        import uuid as _uuid
        from datetime import datetime, timezone

        data = {
            "id": _uuid.uuid4(),
            "name": "m1",
            "enabled": True,
            "is_default": False,
            "address": "salt.local",
            "publish_port": 4505,
            "ret_port": 4506,
            "salt_api_port": None,  # simulate pre-migration NULL
            "use_tls": True,
            "api_url": None,
            "api_user": None,
            "control_mode": "salt_api",
            "api_eauth": "pam",
            "token_delivery": "ingest",
            "tls_verify": False,
            "auto_accept": True,
            "status": "unknown",
            "last_checked_at": None,
            "last_error": None,
            "checks": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        resp = SaltMasterResponse(**data)
        assert resp.salt_api_port == 4507


class TestSaltMasterUpdateSchema:
    def test_has_salt_api_port_and_use_tls(self):
        schema = SaltMasterUpdate(salt_api_port=9443, use_tls=False)
        assert schema.salt_api_port == 9443
        assert schema.use_tls is False

    def test_control_mode_not_in_schema(self):
        fields = SaltMasterUpdate.model_fields
        assert "control_mode" not in fields, "control_mode should not be in SaltMasterUpdate"

    def test_api_eauth_not_in_schema(self):
        fields = SaltMasterUpdate.model_fields
        assert "api_eauth" not in fields, "api_eauth should not be in SaltMasterUpdate"

    def test_token_delivery_not_in_schema(self):
        fields = SaltMasterUpdate.model_fields
        assert "token_delivery" not in fields, "token_delivery should not be in SaltMasterUpdate"

    def test_api_url_not_in_update_schema(self):
        fields = SaltMasterUpdate.model_fields
        assert "api_url" not in fields, "api_url should not be in SaltMasterUpdate (it is derived)"


class TestSaltMasterResponseSchema:
    def test_api_url_present_in_response(self):
        """api_url must be present in Response as a read-only derived field."""
        fields = SaltMasterResponse.model_fields
        assert "api_url" in fields, "api_url must be in SaltMasterResponse (read-only derived)"

    def test_salt_api_port_present_in_response(self):
        fields = SaltMasterResponse.model_fields
        assert "salt_api_port" in fields

    def test_use_tls_present_in_response(self):
        fields = SaltMasterResponse.model_fields
        assert "use_tls" in fields

    def test_response_validates_from_orm_like_dict(self):
        data = {
            "id": uuid.uuid4(),
            "name": "mm1",
            "enabled": True,
            "is_default": True,
            "address": "salt.local",
            "publish_port": 4505,
            "ret_port": 4506,
            "salt_api_port": 8080,
            "use_tls": True,
            "api_url": "https://salt.local:8080",
            "api_user": "saltadmin",
            "control_mode": "salt_api",
            "api_eauth": "pam",
            "token_delivery": "ingest",
            "tls_verify": False,
            "auto_accept": True,
            "status": "ok",
            "last_checked_at": None,
            "last_error": None,
            "checks": None,
            "created_at": "2026-06-07T00:00:00+00:00",
            "updated_at": "2026-06-07T00:00:00+00:00",
        }
        resp = SaltMasterResponse(**data)
        assert resp.api_url == "https://salt.local:8080"
        assert resp.salt_api_port == 8080
        assert resp.use_tls is True


# ---------------------------------------------------------------------------
# 3. salt_tasks: resolves creds from DB, not env
# ---------------------------------------------------------------------------


class TestSaltTasksDbResolution:
    def _make_master(
        self,
        api_url="https://salt.local:8080",
        api_user="admin",
        api_password_enc=None,
        api_eauth="pam",
        tls_verify=False,
        is_default=True,
        enabled=True,
    ):
        m = MagicMock()
        m.id = uuid.uuid4()
        m.api_url = api_url
        m.api_user = api_user
        m.api_password_enc = api_password_enc
        m.api_eauth = api_eauth
        m.tls_verify = tls_verify
        m.is_default = is_default
        m.enabled = enabled
        return m

    def _make_mock_db_ctx(self, scalar_value):
        """Return a context manager mock that yields a DB session returning scalar_value."""
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = scalar_value
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mock_db)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    def test_get_default_master_returns_none_when_db_empty(self):
        """_get_default_master returns None when no master row exists."""
        # _get_default_master does `from fleet_platform.db.session import get_sync_db` locally
        from fleet_platform.db import session as db_session

        with patch.object(db_session, "get_sync_db", return_value=self._make_mock_db_ctx(None)):
            result = salt_tasks._get_default_master()
        assert result is None

    def test_get_default_master_returns_creds_from_row(self):
        """_get_default_master extracts api_url, api_user, tls_verify from the ORM row."""
        master = self._make_master(api_url="https://salt.local:8080", api_user="saltadmin", tls_verify=True)
        from fleet_platform.db import session as db_session

        with patch.object(db_session, "get_sync_db", return_value=self._make_mock_db_ctx(master)):
            result = salt_tasks._get_default_master()
        assert result is not None
        assert result["api_url"] == "https://salt.local:8080"
        assert result["api_user"] == "saltadmin"
        assert result["tls_verify"] is True

    def test_run_salt_api_passes_tls_verify_to_requests(self):
        """_run_salt_api passes verify=tls_verify from the DB row to requests.post."""
        master_creds = {
            "api_url": "https://salt.local:8080",
            "api_user": "admin",
            "api_password": "secret",
            "api_eauth": "pam",
            "tls_verify": True,
        }
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"return": [{"minion1": True}]}
        with (
            patch.object(salt_tasks, "_get_default_master", return_value=master_creds),
            patch("fleet_platform.workers.salt_tasks.requests.post", return_value=mock_response) as mock_post,
        ):
            result = salt_tasks._run_salt_api(function="test.ping", target="minion1")

        assert result["status"] == "ok"
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs.get("verify") is True, "verify=tls_verify must be passed to requests.post"

    def test_no_master_returns_not_configured_error(self):
        """When no master exists, _run_salt_api returns the 'not configured' error."""
        with patch.object(salt_tasks, "_get_default_master", return_value=None):
            result = salt_tasks._run_salt_api(function="test.ping", target="minion1")
        assert result["status"] == "error"
        assert "Settings → Salt Masters" in result["reason"]


# ---------------------------------------------------------------------------
# 4. Behavioral: salt_tasks reads credentials from DB, ignores env vars (#562)
# ---------------------------------------------------------------------------


class TestGrepGuardSaltTasks:
    """Verify salt_tasks resolves salt-api credentials from DB, not SALT_API_* env vars (#562)."""

    def _make_master_creds(self, api_url="https://db-master:8080", api_user="db-admin"):
        return {
            "api_url": api_url,
            "api_user": api_user,
            "api_password": "",
            "api_eauth": "pam",
            "tls_verify": False,
        }

    def test_no_salt_api_url_env_read(self, monkeypatch):
        """salt_tasks must use DB api_url, not SALT_API_URL env var (#562)."""
        monkeypatch.setenv("SALT_API_URL", "http://env-url-must-not-be-used:9999")
        creds = self._make_master_creds(api_url="https://db-master:8080")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"return": [{"minion1": True}]}

        with (
            patch.object(salt_tasks, "_get_default_master", return_value=creds),
            patch("fleet_platform.workers.salt_tasks.requests.post", return_value=mock_response) as mock_post,
        ):
            salt_tasks._run_salt_api(function="test.ping", target="minion1")

        called_url = mock_post.call_args[0][0]
        assert "db-master" in called_url, (
            f"salt_tasks must use DB api_url, not SALT_API_URL env var. Called: {called_url!r}"
        )
        assert "env-url-must-not-be-used" not in called_url

    def test_no_salt_api_user_env_read(self, monkeypatch):
        """salt_tasks must use DB api_user, not SALT_API_USER env var (#562)."""
        monkeypatch.setenv("SALT_API_USER", "env-user-must-not-be-used")
        creds = self._make_master_creds(api_user="db-admin-user")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"return": [{"minion1": True}]}

        with (
            patch.object(salt_tasks, "_get_default_master", return_value=creds),
            patch("fleet_platform.workers.salt_tasks.requests.post", return_value=mock_response) as mock_post,
        ):
            salt_tasks._run_salt_api(function="test.ping", target="minion1")

        # Verify the post body uses the DB user, not the env var
        call_kwargs = mock_post.call_args
        post_body = call_kwargs[1].get("json", call_kwargs[1].get("data", {}))
        username_used = post_body.get("username", "") if isinstance(post_body, dict) else ""
        assert username_used != "env-user-must-not-be-used", (
            "salt_tasks must use DB api_user, not SALT_API_USER env var (#562)"
        )
        assert username_used == "db-admin-user"

    def test_no_salt_api_password_env_read(self, monkeypatch):
        """salt_tasks must NOT read api credentials from SALT_API_PASSWORD env var (#562)."""
        monkeypatch.setenv("SALT_API_PASSWORD", "env-password-must-not-be-used")
        creds = self._make_master_creds()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"return": [{"minion1": True}]}

        with (
            patch.object(salt_tasks, "_get_default_master", return_value=creds),
            patch("fleet_platform.workers.salt_tasks.requests.post", return_value=mock_response) as mock_post,
        ):
            result = salt_tasks._run_salt_api(function="test.ping", target="minion1")

        # The call must succeed using DB creds; env var must have no effect
        assert result["status"] == "ok", f"Expected ok, got {result!r}"
        call_kwargs = mock_post.call_args
        post_body = call_kwargs[1].get("json", call_kwargs[1].get("data", {}))
        password_used = post_body.get("password", "") if isinstance(post_body, dict) else ""
        assert password_used != "env-password-must-not-be-used", (
            "salt_tasks must not use SALT_API_PASSWORD env var (#562)"
        )

    def test_no_os_environ_get_salt_api(self, monkeypatch):
        """When all SALT_API_* env vars are set, salt_tasks still uses DB credentials (#562)."""
        monkeypatch.setenv("SALT_API_URL", "http://env-trap:9999")
        monkeypatch.setenv("SALT_API_USER", "env-trap-user")
        monkeypatch.setenv("SALT_API_PASSWORD", "env-trap-pass")

        # Return None → "not configured" path; if env vars are read, the error message would differ
        with patch.object(salt_tasks, "_get_default_master", return_value=None):
            result = salt_tasks._run_salt_api(function="test.ping", target="*")

        assert result["status"] == "error"
        assert "Settings → Salt Masters" in result["reason"], (
            "When no DB master exists, error must reference Settings (not env vars) (#562)"
        )


# ---------------------------------------------------------------------------
# 5. Grep-guard: ansible_tasks._get_bootstrap_settings does not read SALT_MASTER
# ---------------------------------------------------------------------------


class TestGrepGuardAnsibleTasks:
    def test_get_bootstrap_settings_does_not_query_salt_master_setting(self):
        """_get_bootstrap_settings must not query the 'SALT_MASTER' platform setting (#562).

        After #562 the master address is resolved from SaltMaster DB rows, not from a
        platform setting called 'SALT_MASTER'.  Drive the function with an instrumented DB
        and assert the key "SALT_MASTER" was never queried.
        """
        queried_keys: list[str] = []

        mock_db = MagicMock()

        def _tracking_execute(stmt):
            stmt_str = str(stmt)
            # Extract the key value from the WHERE clause string representation
            if "SALT_MASTER" in stmt_str:
                queried_keys.append("SALT_MASTER")
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r

        mock_db.execute.side_effect = _tracking_execute

        with (
            patch("fleet_platform.services.platform_settings_svc._fernet", MagicMock()),
            patch("fleet_platform.services.node_credentials.get_controller_pubkey", return_value="ssh-rsa AAAA"),
        ):
            ansible_tasks._get_bootstrap_settings(mock_db)

        assert "SALT_MASTER" not in queried_keys, (
            "_get_bootstrap_settings must not query the SALT_MASTER platform setting — "
            "the address must come from SaltMaster rows only (#562)"
        )

    def test_get_bootstrap_settings_returns_three_values(self):
        """Signature must return (ssh_user, ssh_password, controller_pubkey) — no salt_master address (#562)."""
        # Call the function with a mock DB and verify it returns exactly 3 values
        mock_db = MagicMock()
        # PlatformSetting rows — return None for all settings queries
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        with (
            patch("fleet_platform.services.platform_settings_svc._fernet", MagicMock()),
            # #750: _get_bootstrap_settings (and its get_controller_pubkey call)
            # moved to fleet_platform.services.node_credentials.
            patch("fleet_platform.services.node_credentials.get_controller_pubkey", return_value="ssh-rsa AAAA"),
        ):
            result = ansible_tasks._get_bootstrap_settings(mock_db)
        assert isinstance(result, tuple), "_get_bootstrap_settings must return a tuple"
        assert len(result) == 3, (
            f"_get_bootstrap_settings must return 3 values (ssh_user, ssh_password, pubkey), got {len(result)}"
        )
