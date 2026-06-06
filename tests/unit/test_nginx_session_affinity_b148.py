"""Tests for #148: nginx WebSocket session affinity and DNS re-resolution.

Architecture note: nginx resolves the 'api' hostname via Docker's embedded DNS
(127.0.0.11). Using a static upstream block caches the IP at startup — if the
API container is redeployed and gets a new IP, nginx keeps trying the old one
and returns 502. The fix uses `resolver 127.0.0.11` + `set $api_upstream` so
nginx re-resolves on every request cycle (valid=5s TTL).
"""

from pathlib import Path


def _nginx() -> str:
    return Path("deploy/nginx.conf").read_text()


def test_nginx_has_docker_resolver():
    """Docker embedded DNS must be configured for dynamic IP re-resolution."""
    src = _nginx()
    assert "127.0.0.11" in src, (
        "resolver 127.0.0.11 is required so nginx re-resolves 'api' after "
        "container restarts instead of caching the stale IP."
    )


def test_nginx_resolver_has_valid_ttl():
    """Resolver must have a short TTL so stale IPs are not cached long."""
    src = _nginx()
    assert "valid=" in src, "resolver must specify a valid= TTL (e.g. valid=5s)"


def test_nginx_uses_variable_proxy_pass():
    """proxy_pass must use a variable to force runtime DNS resolution."""
    src = _nginx()
    assert "set $api_upstream" in src, (
        "proxy_pass must use `set $api_upstream http://api:8000` so nginx "
        "re-resolves DNS dynamically. Static proxy_pass caches the IP."
    )


def test_nginx_websocket_location_exists():
    src = _nginx()
    assert "/api/v1/(ssh|vnc)/session/" in src or "ssh|vnc" in src


def test_nginx_websocket_upgrade_headers():
    src = _nginx()
    assert "proxy_set_header Upgrade $http_upgrade" in src
    assert 'proxy_set_header Connection "upgrade"' in src


def test_nginx_websocket_timeout_extended():
    src = _nginx()
    assert "3600s" in src


def test_nginx_api_location_proxies_to_api():
    src = _nginx()
    assert "http://api:8000" in src, "Must proxy to 'api:8000' hostname"


def test_nginx_spa_fallback_preserved():
    assert "try_files $uri $uri/ /index.html" in _nginx()
