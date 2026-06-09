"""
Unit tests for TLS-verification support in process_collector — GitHub issue #639.

Tests three concerns:
  1. _ssl_context(True)  → None  (system default, full cert verification)
  2. _ssl_context(False) → ssl.SSLContext with CERT_NONE (self-signed / internal certs)
  3. Source-contract: post() reads INGEST_TLS_VERIFY and passes context= to urlopen

No psutil required; the module is imported via importlib the same way as the
existing test_process_collector_610.py so the lazy-import pattern is respected.
"""

import importlib.util
import ssl
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Load the collector module by file path (no psutil needed)
# ---------------------------------------------------------------------------

_COLLECTOR_PATH = (
    Path(__file__).parent.parent.parent
    / "salt"
    / "states"
    / "base"
    / "files"
    / "process_collector.py"
)


def _load_collector():
    spec = importlib.util.spec_from_file_location("process_collector", _COLLECTOR_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def collector():
    return _load_collector()


@pytest.fixture(scope="module")
def collector_source():
    return _COLLECTOR_PATH.read_text()


# ---------------------------------------------------------------------------
# _ssl_context — behavioural tests
# ---------------------------------------------------------------------------


class TestSslContext:
    def test_verify_true_returns_none(self, collector):
        """When verify=True the helper returns None so urllib uses its default."""
        result = collector._ssl_context(True)
        assert result is None

    def test_verify_false_returns_ssl_context(self, collector):
        """When verify=False the helper returns an ssl.SSLContext instance."""
        ctx = collector._ssl_context(False)
        assert isinstance(ctx, ssl.SSLContext)

    def test_verify_false_cert_none(self, collector):
        """The unverified context must have CERT_NONE so self-signed certs are accepted."""
        ctx = collector._ssl_context(False)
        assert ctx.verify_mode == ssl.CERT_NONE


# ---------------------------------------------------------------------------
# post() — source-contract checks
# ---------------------------------------------------------------------------


class TestPostSourceContract:
    """Grep-level source-contract: post() must wire up INGEST_TLS_VERIFY + context=."""

    def test_reads_ingest_tls_verify_env_var(self, collector_source):
        """post() source must reference the INGEST_TLS_VERIFY env var."""
        assert "INGEST_TLS_VERIFY" in collector_source

    def test_passes_context_to_urlopen(self, collector_source):
        """post() source must pass context= to urlopen."""
        assert "context=ctx" in collector_source or "context=" in collector_source

    def test_calls_ssl_context_helper(self, collector_source):
        """post() source must call _ssl_context to build the context."""
        assert "_ssl_context(" in collector_source

    def test_falsy_env_values_documented(self, collector_source):
        """The docstring / module body must list the accepted falsy values."""
        assert '"false"' in collector_source or "'false'" in collector_source
        assert '"no"' in collector_source or "'no'" in collector_source
        assert '"0"' in collector_source or "'0'" in collector_source


# ---------------------------------------------------------------------------
# post() — behavioural: env var controls the context passed to urlopen
# ---------------------------------------------------------------------------


class TestPostTlsVerifyBehaviour:
    """Verify that post() passes the right ssl context to urlopen based on env."""

    def _make_mock_response(self):
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_tls_verify_true_by_default_passes_none_context(self, collector):
        """With INGEST_TLS_VERIFY unset (default), context passed to urlopen is None."""
        with patch.dict("os.environ", {}, clear=False):
            # Remove the var if it happens to be set
            import os

            os.environ.pop("INGEST_TLS_VERIFY", None)
            with patch("urllib.request.urlopen", return_value=self._make_mock_response()) as mock_open:
                collector.post("https://example.com/api/v1/ingest", "tok", "minion1", [])
        _args, kwargs = mock_open.call_args
        assert kwargs.get("context") is None

    def test_tls_verify_false_passes_ssl_context(self, collector):
        """With INGEST_TLS_VERIFY=false, context passed to urlopen is an SSLContext."""
        with patch.dict("os.environ", {"INGEST_TLS_VERIFY": "false"}):
            with patch("urllib.request.urlopen", return_value=self._make_mock_response()) as mock_open:
                collector.post("https://example.com/api/v1/ingest", "tok", "minion1", [])
        _args, kwargs = mock_open.call_args
        assert isinstance(kwargs.get("context"), ssl.SSLContext)

    def test_tls_verify_zero_passes_ssl_context(self, collector):
        """With INGEST_TLS_VERIFY=0, context is an SSLContext (falsy value)."""
        with patch.dict("os.environ", {"INGEST_TLS_VERIFY": "0"}):
            with patch("urllib.request.urlopen", return_value=self._make_mock_response()) as mock_open:
                collector.post("https://example.com/api/v1/ingest", "tok", "minion1", [])
        _args, kwargs = mock_open.call_args
        assert isinstance(kwargs.get("context"), ssl.SSLContext)

    def test_tls_verify_no_passes_ssl_context(self, collector):
        """With INGEST_TLS_VERIFY=no, context is an SSLContext (falsy value)."""
        with patch.dict("os.environ", {"INGEST_TLS_VERIFY": "no"}):
            with patch("urllib.request.urlopen", return_value=self._make_mock_response()) as mock_open:
                collector.post("https://example.com/api/v1/ingest", "tok", "minion1", [])
        _args, kwargs = mock_open.call_args
        assert isinstance(kwargs.get("context"), ssl.SSLContext)
