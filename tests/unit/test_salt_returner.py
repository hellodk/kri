# tests/unit/test_salt_returner.py
import importlib.util
from unittest.mock import MagicMock, patch


def _load_returner(ingest_url="http://fleet.local/api/v1/ingest", node_token="test-token"):
    """Load the Salt returner module with mocked __salt__ dunder global."""
    spec = importlib.util.spec_from_file_location(
        "fleet_platform_return",
        "salt/returners/fleet_platform_return.py",
    )
    module = importlib.util.module_from_spec(spec)
    module.__salt__ = {
        "config.get": lambda key, default=None: {
            "fleet_platform.ingest_url": ingest_url,
            "fleet_platform.node_token": node_token,
        }.get(key, default),
    }
    spec.loader.exec_module(module)
    return module


def test_returner_posts_to_executions_endpoint():
    module = _load_returner()
    ret = {
        "id": "mac-mini-01.local",
        "jid": "20260512100000123456",
        "return": {"test.ping": True},
        "retcode": 0,
        "fun": "test.ping",
        "success": True,
    }
    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp
        module.returner(ret)
        mock_open.assert_called_once()
        req = mock_open.call_args[0][0]
        assert "/executions" in req.full_url


def test_returner_skips_when_not_configured():
    module = _load_returner(ingest_url=None, node_token=None)
    module.__salt__ = {"config.get": lambda key, default=None: None}
    with patch("urllib.request.urlopen") as mock_open:
        module.returner({"id": "test", "jid": "123", "return": {}})
        mock_open.assert_not_called()


def test_returner_handles_network_error_gracefully():
    import urllib.error
    module = _load_returner()
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        # Should not raise — just log the error
        module.returner({
            "id": "mac-mini-01.local",
            "jid": "123",
            "return": {},
            "retcode": 0,
            "fun": "test.ping",
        })


def test_required_functions_exist():
    """Salt requires these functions to be present in a returner module."""
    module = _load_returner()
    assert callable(getattr(module, "returner", None))
    assert callable(getattr(module, "prep_jid", None))
    assert callable(getattr(module, "save_load", None))
    assert callable(getattr(module, "get_load", None))
