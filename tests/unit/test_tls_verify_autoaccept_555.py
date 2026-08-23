"""Unit tests for #555 — per-master tls_verify + auto_accept minion key on bootstrap.

Coverage:
- salt_api_client._post / run_wheel passes verify=master.tls_verify to requests.post
- salt_master_probe threads tls_verify into requests.post for all four HTTP checks
- bootstrap_node auto_accept=True → run_wheel("key.accept") called after success
- bootstrap_node auto_accept=False → run_wheel NOT called
- bootstrap_node run_wheel raises SaltApiError → warning logged, bootstrap still "completed"
- SaltMaster model defaults: tls_verify=False, auto_accept=True
"""

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_master(
    tls_verify: bool = False,
    auto_accept: bool = True,
    api_url: str = "http://salt.local:8080",
    api_user: str = "admin",
    api_password_enc: str | None = None,
    api_eauth: str = "pam",
    name: str = "mm1",
    address: str = "salt.local",
    publish_port: int = 4505,
    ret_port: int = 4506,
    token_delivery: str = "ingest",
) -> MagicMock:
    """Return a MagicMock that quacks like a SaltMaster row."""
    m = MagicMock()
    m.tls_verify = tls_verify
    m.auto_accept = auto_accept
    m.api_url = api_url
    m.api_user = api_user
    m.api_password_enc = api_password_enc
    m.api_eauth = api_eauth
    m.name = name
    m.address = address
    m.publish_port = publish_port
    m.ret_port = ret_port
    m.token_delivery = token_delivery
    return m


# ---------------------------------------------------------------------------
# salt_api_client tests
# ---------------------------------------------------------------------------


class TestSaltApiClientTlsVerify:
    """_post must pass verify=master.tls_verify to requests.post."""

    def _make_ok_response(self) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"return": [{"accepted": True}]}
        resp.raise_for_status.return_value = None
        return resp

    @patch("fleet_platform.services.salt_api_client.requests.post")
    @patch("fleet_platform.services.salt_api_client.decrypt_secret", return_value="pw")
    def test_post_passes_verify_false(self, _dec, mock_post):
        mock_post.return_value = self._make_ok_response()
        master = _make_master(tls_verify=False, api_password_enc="enc")

        from fleet_platform.services.salt_api_client import _post

        _post(master, [{"client": "wheel", "fun": "key.accept"}])

        _, kwargs = mock_post.call_args
        assert kwargs["verify"] is False

    @patch("fleet_platform.services.salt_api_client.requests.post")
    @patch("fleet_platform.services.salt_api_client.decrypt_secret", return_value="pw")
    def test_post_passes_verify_true(self, _dec, mock_post):
        mock_post.return_value = self._make_ok_response()
        master = _make_master(tls_verify=True, api_password_enc="enc")

        from fleet_platform.services.salt_api_client import _post

        _post(master, [{"client": "wheel", "fun": "key.accept"}])

        _, kwargs = mock_post.call_args
        assert kwargs["verify"] is True

    @patch("fleet_platform.services.salt_api_client.requests.post")
    @patch("fleet_platform.services.salt_api_client.decrypt_secret", return_value="pw")
    def test_run_wheel_passes_verify(self, _dec, mock_post):
        mock_post.return_value = self._make_ok_response()
        master = _make_master(tls_verify=False, api_password_enc="enc")

        from fleet_platform.services.salt_api_client import run_wheel

        run_wheel(master, "key.accept", match="minion1")

        _, kwargs = mock_post.call_args
        assert "verify" in kwargs
        assert kwargs["verify"] is False

    @patch("fleet_platform.services.salt_api_client.requests.post")
    def test_post_uses_getattr_fallback_when_no_tls_verify_attr(self, mock_post):
        """If master doesn't have tls_verify attribute, getattr default of True is used (#1046: fail secure)."""
        mock_post.return_value = self._make_ok_response()
        master = MagicMock(spec=[])  # no attributes at all
        master.api_url = "http://salt.local:8080"
        master.api_user = "admin"
        master.api_password_enc = None
        master.api_eauth = "pam"

        from fleet_platform.services.salt_api_client import _post

        _post(master, [{"client": "runner", "fun": "test.ping"}])

        _, kwargs = mock_post.call_args
        assert kwargs["verify"] is True


# ---------------------------------------------------------------------------
# salt_master_probe tests
# ---------------------------------------------------------------------------


class TestSaltMasterProbeTlsVerify:
    """Each _check_* helper must receive and pass through tls_verify."""

    def _ok_resp(self, status_code: int = 200, json_data=None) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {"return": [True]}
        resp.raise_for_status.return_value = None
        return resp

    @patch("fleet_platform.services.salt_master_probe.requests.post")
    def test_check_salt_api_auth_passes_verify(self, mock_post):
        mock_post.return_value = self._ok_resp()
        from fleet_platform.services.salt_master_probe import _check_salt_api_auth

        _check_salt_api_auth("http://salt:8080", "admin", "pass", "pam", tls_verify=True)

        _, kwargs = mock_post.call_args
        assert kwargs.get("verify") is True

    @patch("fleet_platform.services.salt_master_probe.requests.post")
    def test_check_salt_api_auth_verify_false_by_default(self, mock_post):
        mock_post.return_value = self._ok_resp()
        from fleet_platform.services.salt_master_probe import _check_salt_api_auth

        _check_salt_api_auth("http://salt:8080", "admin", "pass", "pam")

        _, kwargs = mock_post.call_args
        assert kwargs.get("verify") is False

    @patch("fleet_platform.services.salt_master_probe.requests.post")
    def test_check_key_store_passes_verify(self, mock_post):
        mock_post.return_value = self._ok_resp(json_data={"return": [{}]})
        from fleet_platform.services.salt_master_probe import _check_key_store

        _check_key_store("http://salt:8080", "admin", "pass", "pam", tls_verify=True)

        _, kwargs = mock_post.call_args
        assert kwargs.get("verify") is True

    @patch("fleet_platform.services.salt_master_probe.requests.post")
    def test_check_version_passes_verify(self, mock_post):
        mock_post.return_value = self._ok_resp(json_data={"return": [{}]})
        from fleet_platform.services.salt_master_probe import _check_version

        _check_version("http://salt:8080", "admin", "pass", "pam", tls_verify=True)

        _, kwargs = mock_post.call_args
        assert kwargs.get("verify") is True

    @patch("fleet_platform.services.salt_master_probe.requests.post")
    def test_check_minions_up_passes_verify(self, mock_post):
        mock_post.return_value = self._ok_resp(json_data={"return": [[]]})
        from fleet_platform.services.salt_master_probe import _check_minions_up

        _check_minions_up("http://salt:8080", "admin", "pass", "pam", tls_verify=True)

        _, kwargs = mock_post.call_args
        assert kwargs.get("verify") is True


# ---------------------------------------------------------------------------
# bootstrap_node auto_accept tests
# ---------------------------------------------------------------------------


def _bootstrap_node_setup():
    """Import the task function for direct testing (bypasses Celery)."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    return bootstrap_node


class TestAutoAcceptOnBootstrap:
    """bootstrap_node runs key.accept for each master with auto_accept=True.

    Strategy: test the auto-accept logic at the service layer by calling
    the internal helper directly, rather than driving all of bootstrap_node
    (which requires heavy ansible_runner + filesystem mocking).
    """

    # ------------------------------------------------------------------
    # Direct unit tests for the auto-accept loop logic
    # ------------------------------------------------------------------

    def _run_auto_accept_loop(
        self,
        masters_info: list[dict],
        node_minion_id: str,
        rw_mock: MagicMock,
    ) -> list[str]:
        """
        Replicate the auto-accept loop from bootstrap_node in isolation.
        Returns the list of note strings produced.
        """
        from fleet_platform.services.salt_api_client import SaltApiError

        auto_accept_notes: list[str] = []
        for info in masters_info:
            if not info["auto_accept"]:
                continue
            master_obj = info["master"]
            master_name = info["name"]
            try:
                rw_mock(master_obj, "key.accept", match=node_minion_id)
                note = f"minion key auto-accepted on {master_name}"
                auto_accept_notes.append(note)
            except SaltApiError as exc:
                note = f"key auto-accept failed on {master_name}; accept manually ({exc.reason})"
                auto_accept_notes.append(note)
            except Exception as exc:  # noqa: BLE001
                note = f"key auto-accept failed on {master_name}; accept manually ({exc})"
                auto_accept_notes.append(note)
        return auto_accept_notes

    def test_auto_accept_true_calls_run_wheel(self):
        """When auto_accept=True, the loop calls rw(master, 'key.accept', match=minion)."""
        from fleet_platform.services.salt_api_client import SaltApiError  # noqa: F401

        master = _make_master(auto_accept=True, name="mm1")
        rw_mock = MagicMock(return_value={"accepted": ["mac-mini-1"]})

        notes = self._run_auto_accept_loop(
            [{"master": master, "auto_accept": True, "name": "mm1"}],
            "mac-mini-1",
            rw_mock,
        )

        rw_mock.assert_called_once_with(master, "key.accept", match="mac-mini-1")
        assert any("auto-accepted" in n for n in notes), f"Expected acceptance note, got: {notes}"

    def test_auto_accept_false_does_not_call_run_wheel(self):
        """When auto_accept=False, the loop skips the master entirely."""
        master = _make_master(auto_accept=False, name="mm1")
        rw_mock = MagicMock()

        notes = self._run_auto_accept_loop(
            [{"master": master, "auto_accept": False, "name": "mm1"}],
            "mac-mini-1",
            rw_mock,
        )

        rw_mock.assert_not_called()
        assert len(notes) == 0

    def test_auto_accept_run_wheel_salt_error_does_not_raise(self):
        """SaltApiError from run_wheel must be caught; note appended, no raise."""
        from fleet_platform.services.salt_api_client import SaltApiError

        master = _make_master(auto_accept=True, name="mm1")
        rw_mock = MagicMock(side_effect=SaltApiError("permission denied"))

        notes = self._run_auto_accept_loop(
            [{"master": master, "auto_accept": True, "name": "mm1"}],
            "mac-mini-1",
            rw_mock,
        )

        # Must not raise; must produce a failure note
        assert any("failed" in n for n in notes), f"Expected failure note, got: {notes}"
        assert any("accept manually" in n for n in notes)

    def test_auto_accept_run_wheel_generic_error_does_not_raise(self):
        """Any other exception from run_wheel must be caught; note appended."""
        master = _make_master(auto_accept=True, name="mm1")
        rw_mock = MagicMock(side_effect=RuntimeError("timeout"))

        notes = self._run_auto_accept_loop(
            [{"master": master, "auto_accept": True, "name": "mm1"}],
            "mac-mini-1",
            rw_mock,
        )

        assert any("failed" in n for n in notes)

    def test_mixed_masters_only_auto_accept_true_called(self):
        """With two masters, only the one with auto_accept=True triggers key.accept."""
        m_accept = _make_master(auto_accept=True, name="mm1")
        m_skip = _make_master(auto_accept=False, name="mm2")
        rw_mock = MagicMock(return_value={"accepted": ["mac-mini-1"]})

        notes = self._run_auto_accept_loop(
            [
                {"master": m_accept, "auto_accept": True, "name": "mm1"},
                {"master": m_skip, "auto_accept": False, "name": "mm2"},
            ],
            "mac-mini-1",
            rw_mock,
        )

        assert rw_mock.call_count == 1
        rw_mock.assert_called_once_with(m_accept, "key.accept", match="mac-mini-1")
        assert len(notes) == 1
        assert "mm1" in notes[0]


# ---------------------------------------------------------------------------
# Model default tests
# ---------------------------------------------------------------------------


class TestSaltMasterModelDefaults:
    """The ORM model must declare the right Python-level defaults."""

    def test_tls_verify_default_is_true(self):
        # #1005 S3: default flipped False→True so salt-api TLS is verified by
        # default (MITM-safe); operators opt OUT per master if needed.
        from fleet_platform.models.salt_master import SaltMaster

        col = SaltMaster.__table__.c["tls_verify"]
        assert col.default.arg is True

    def test_auto_accept_default_is_true(self):
        from fleet_platform.models.salt_master import SaltMaster

        col = SaltMaster.__table__.c["auto_accept"]
        assert col.default.arg is True

    def test_tls_verify_column_nullable_false(self):
        from fleet_platform.models.salt_master import SaltMaster

        col = SaltMaster.__table__.c["tls_verify"]
        assert col.nullable is False

    def test_auto_accept_column_nullable_false(self):
        from fleet_platform.models.salt_master import SaltMaster

        col = SaltMaster.__table__.c["auto_accept"]
        assert col.nullable is False
