"""Tests for salt-api-based grain collection (#708).

collect_node_grains now fetches grains over salt-api (grains.items via the local
client) using the node's master — no SSH and no controller key. SSH salt-call
remains only as a fallback. These tests cover the salt-api helper and the
collect_node_grains happy path.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# _grains_via_salt_api
# ---------------------------------------------------------------------------

CREDS = {
    "api_url": "https://salt.local:4507",
    "api_user": "krisalt",
    "api_password": "pw",
    "api_eauth": "pam",
    "tls_verify": False,
}


def test_grains_via_salt_api_success():
    """A well-formed grains.items return yields the grains dict."""
    from fleet_platform.workers.ansible_tasks import _grains_via_salt_api

    resp = MagicMock()
    resp.json.return_value = {"return": [{"mm1": {"os": "MacOS", "osrelease": "15.0"}}]}
    resp.raise_for_status = MagicMock()
    with patch("requests.post", return_value=resp):
        grains, reason = _grains_via_salt_api(CREDS, "mm1")
    assert reason is None
    assert grains == {"os": "MacOS", "osrelease": "15.0"}


def test_grains_via_salt_api_empty_means_not_connected():
    """An empty return (minion offline / key not accepted) is a soft failure."""
    from fleet_platform.workers.ansible_tasks import _grains_via_salt_api

    resp = MagicMock()
    resp.json.return_value = {"return": [{}]}
    resp.raise_for_status = MagicMock()
    with patch("requests.post", return_value=resp):
        grains, reason = _grains_via_salt_api(CREDS, "mm1")
    assert grains is None
    assert "not connected" in reason


def test_grains_via_salt_api_http_error_returns_reason():
    """Transport/HTTP errors are returned as a reason, never raised."""
    from fleet_platform.workers.ansible_tasks import _grains_via_salt_api

    with patch("requests.post", side_effect=ConnectionError("refused")):
        grains, reason = _grains_via_salt_api(CREDS, "mm1")
    assert grains is None
    assert reason


def test_grains_via_salt_api_requires_api_url():
    """No api_url -> immediate soft failure, no HTTP call."""
    from fleet_platform.workers.ansible_tasks import _grains_via_salt_api

    grains, reason = _grains_via_salt_api({"api_url": "", "api_user": ""}, "mm1")
    assert grains is None
    assert "not configured" in reason


# ---------------------------------------------------------------------------
# collect_node_grains — salt-api happy path (no SSH, no controller key)
# ---------------------------------------------------------------------------


def _ctx_returning(scalar_values):
    """get_sync_db() context whose execute().scalar_one_or_none() pops values."""
    scalar = MagicMock()
    scalar.scalar_one_or_none.side_effect = list(scalar_values)
    db = MagicMock()
    db.execute.return_value = scalar
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def test_collect_node_grains_uses_salt_api(tmp_path: Path):
    """Happy path: grains fetched via salt-api and pushed to ingest as via=salt-api."""
    import fleet_platform.workers.ansible_tasks as mod

    node = MagicMock()
    node.bootstrap_ip = "192.168.1.50"
    node.minion_id = "mm1"
    node.ssh_host_key = None
    node.salt_master_id = None

    # pillar file with a node token
    (tmp_path / "mm1.sls").write_text("node_token: tok-123\n")

    # node query -> node; KRI_API_URL setting query -> None
    ctx = _ctx_returning([node, None])

    urlopen_resp = MagicMock()
    urlopen_resp.status = 200
    urlopen_cm = MagicMock()
    urlopen_cm.__enter__ = MagicMock(return_value=urlopen_resp)
    urlopen_cm.__exit__ = MagicMock(return_value=False)

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", return_value=ctx),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", None, "password")),
        patch("fleet_platform.workers.ansible_tasks._get_pillar_dir", return_value=tmp_path),
        patch("fleet_platform.workers.ansible_tasks._resolve_node_master_creds", return_value=CREDS),
        patch("fleet_platform.workers.ansible_tasks._grains_via_salt_api", return_value=({"os": "MacOS"}, None)),
        patch("urllib.request.urlopen", return_value=urlopen_cm) as mock_urlopen,
    ):
        result = mod.collect_node_grains.run(str(__import__("uuid").uuid4()))

    assert result["status"] == "ok"
    assert result["via"] == "salt-api"
    assert result["http_status"] == 200
    mock_urlopen.assert_called_once()


def test_collect_node_grains_falls_back_to_ssh(tmp_path: Path):
    """When salt-api can't reach the minion, SSH salt-call is used (via=ssh)."""
    import fleet_platform.workers.ansible_tasks as mod

    node = MagicMock()
    node.bootstrap_ip = "192.168.1.50"
    node.minion_id = "mm1"
    node.ssh_host_key = None
    node.salt_master_id = None

    (tmp_path / "mm1.sls").write_text("node_token: tok-123\n")
    ctx = _ctx_returning([node, None])

    urlopen_resp = MagicMock()
    urlopen_resp.status = 200
    urlopen_cm = MagicMock()
    urlopen_cm.__enter__ = MagicMock(return_value=urlopen_resp)
    urlopen_cm.__exit__ = MagicMock(return_value=False)

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", return_value=ctx),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", None, "password")),
        patch("fleet_platform.workers.ansible_tasks._get_pillar_dir", return_value=tmp_path),
        patch("fleet_platform.workers.ansible_tasks._resolve_node_master_creds", return_value=CREDS),
        patch("fleet_platform.workers.ansible_tasks._grains_via_salt_api", return_value=(None, "minion not connected")),
        patch("fleet_platform.workers.ansible_tasks._grains_via_ssh", return_value=({"os": "MacOS"}, None)),
        patch("urllib.request.urlopen", return_value=urlopen_cm),
    ):
        result = mod.collect_node_grains.run(str(__import__("uuid").uuid4()))

    assert result["status"] == "ok"
    assert result["via"] == "ssh"


def test_collect_node_grains_reports_both_failures(tmp_path: Path):
    """When both paths fail, the combined reason is returned (not a misleading SSH msg)."""
    import fleet_platform.workers.ansible_tasks as mod

    node = MagicMock()
    node.bootstrap_ip = "192.168.1.50"
    node.minion_id = "mm1"
    node.ssh_host_key = None
    node.salt_master_id = None
    ctx = _ctx_returning([node, None])

    with (
        patch("fleet_platform.workers.ansible_tasks.get_sync_db", return_value=ctx),
        patch("fleet_platform.workers.ansible_tasks._get_node_credentials", return_value=("admin", None, "password")),
        patch("fleet_platform.workers.ansible_tasks._get_pillar_dir", return_value=tmp_path),
        patch("fleet_platform.workers.ansible_tasks._resolve_node_master_creds", return_value=CREDS),
        patch("fleet_platform.workers.ansible_tasks._grains_via_salt_api", return_value=(None, "minion not connected")),
        patch("fleet_platform.workers.ansible_tasks._grains_via_ssh", return_value=(None, "no controller key")),
    ):
        result = mod.collect_node_grains.run(str(__import__("uuid").uuid4()))

    assert result["status"] == "error"
    assert "salt-api" in result["reason"]
    assert "ssh" in result["reason"]
