"""Tests for salt minion presence sync (#254)."""

from unittest.mock import MagicMock, patch


def test_sync_minion_presence_skips_when_no_salt_api_url():
    """Task returns 'skipped' when SALT_API_URL is not configured."""
    with patch.dict("os.environ", {"SALT_API_URL": ""}):
        # Re-import to pick up patched env
        import importlib

        import fleet_platform.workers.salt_presence_tasks as mod

        importlib.reload(mod)

        result = mod.sync_minion_presence()
        assert result["status"] == "skipped"


def test_runner_call_returns_none_on_connection_error():
    """_runner_call returns None (not raises) on any error."""
    import fleet_platform.workers.salt_presence_tasks as mod

    with (
        patch.object(mod, "_SALT_API_URL", "http://salt-api:8000"),
        patch("requests.post", side_effect=ConnectionError("refused")),
    ):
        result = mod._runner_call("manage.up")
        assert result is None


def test_runner_call_parses_list_response():
    """_runner_call extracts minion list from salt-api response."""
    import fleet_platform.workers.salt_presence_tasks as mod

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"return": [["mm1", "mm2", "mm3"]]}
    mock_resp.raise_for_status = MagicMock()
    with patch.object(mod, "_SALT_API_URL", "http://salt-api:8000"), patch("requests.post", return_value=mock_resp):
        result = mod._runner_call("manage.up")
    assert result == ["mm1", "mm2", "mm3"]


def test_runner_call_parses_dict_response():
    """_runner_call handles dict-keyed response format from some salt-api versions."""
    import fleet_platform.workers.salt_presence_tasks as mod

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"return": [{"mm1": True, "mm2": True}]}
    mock_resp.raise_for_status = MagicMock()
    with patch.object(mod, "_SALT_API_URL", "http://salt-api:8000"), patch("requests.post", return_value=mock_resp):
        result = mod._runner_call("manage.up")
    assert set(result) == {"mm1", "mm2"}


def test_sync_presence_in_beat_schedule():
    """sync-minion-presence must be registered in the celery beat schedule."""
    from fleet_platform.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "sync-minion-presence" in schedule
    task = schedule["sync-minion-presence"]["task"]
    assert "salt_presence" in task
    assert schedule["sync-minion-presence"]["schedule"] <= 120  # runs at least every 2 min
