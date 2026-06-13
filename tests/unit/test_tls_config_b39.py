"""Tests for #131: TLS configuration."""

from pathlib import Path

TLS_CONF = (Path(__file__).parent.parent.parent / "deploy/nginx-tls.conf.template").read_text()
RUNBOOK = (Path(__file__).parent.parent.parent / "docs/OPS_RUNBOOK.md").read_text()
GITIGNORE = (Path(__file__).parent.parent.parent / ".gitignore").read_text()


def test_tls_conf_listens_443():
    assert "443 ssl" in TLS_CONF or "443" in TLS_CONF


def test_tls_conf_redirects_http():
    assert "301" in TLS_CONF or "return 301" in TLS_CONF


def test_tls_conf_has_hsts():
    assert "Strict-Transport-Security" in TLS_CONF


def test_tls_conf_has_modern_protocols():
    assert "TLSv1.2" in TLS_CONF or "TLSv1.3" in TLS_CONF


def test_tls_conf_has_websocket_upgrade():
    assert "Upgrade" in TLS_CONF


def test_tls_conf_sets_forwarded_proto():
    assert "X-Forwarded-Proto" in TLS_CONF


def test_gen_cert_script_exists():
    script = Path(__file__).parent.parent.parent / "scripts/gen_self_signed_cert.sh"
    assert script.exists()
    assert "openssl" in script.read_text()


def test_certs_dir_gitignored():
    assert "certs" in GITIGNORE or "deploy/certs" in GITIGNORE


def test_runbook_documents_tls():
    assert "TLS" in RUNBOOK or "tls" in RUNBOOK.lower() or "https" in RUNBOOK.lower()
