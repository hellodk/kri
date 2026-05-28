"""Tests for #148: nginx WebSocket session affinity."""
from pathlib import Path


def _nginx() -> str:
    return Path("deploy/nginx.conf").read_text()


def test_nginx_has_upstream_block():
    assert "upstream api_backend" in _nginx()


def test_nginx_upstream_has_ip_hash():
    src = _nginx()
    upstream_idx = src.index("upstream api_backend")
    upstream_block = src[upstream_idx:upstream_idx + 200]
    assert "ip_hash" in upstream_block


def test_nginx_websocket_location_exists():
    src = _nginx()
    assert "/api/v1/(ssh|vnc)/session/" in src or "ssh|vnc" in src


def test_nginx_websocket_upgrade_headers():
    src = _nginx()
    assert 'proxy_set_header Upgrade $http_upgrade' in src
    assert 'proxy_set_header Connection "upgrade"' in src


def test_nginx_websocket_timeout_extended():
    src = _nginx()
    assert "3600s" in src


def test_nginx_api_location_still_proxies():
    src = _nginx()
    assert "proxy_pass http://api_backend" in src


def test_nginx_no_stale_resolver_trick():
    src = _nginx()
    # The old set $api_upstream hack shouldn't be needed with upstream block
    assert "set $api_upstream" not in src


def test_nginx_spa_fallback_preserved():
    assert "try_files $uri $uri/ /index.html" in _nginx()
