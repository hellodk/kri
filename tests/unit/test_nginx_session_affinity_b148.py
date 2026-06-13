"""Tests for #148: nginx WebSocket session affinity and DNS re-resolution.

Architecture note: nginx resolves the 'api' hostname via the container
runtime's embedded DNS. Using a static upstream block caches the IP at
startup — if the API container is redeployed and gets a new IP, nginx
keeps trying the old one and returns 502. The fix uses
`resolver ${NGINX_RESOLVER}` + `set $api_upstream` so nginx re-resolves
on every request cycle (valid=5s TTL). NGINX_RESOLVER is substituted at
container start (Docker default 127.0.0.11; Podman/k8s override).
"""

from pathlib import Path


def _nginx() -> str:
    return Path("deploy/nginx.conf.template").read_text()


def _dockerfile() -> str:
    return Path("deploy/Dockerfile.frontend").read_text()


def test_nginx_resolver_is_parameterized():
    """Resolver must reference an env var so Docker / Podman / k8s can override it."""
    src = _nginx()
    assert "${NGINX_RESOLVER}" in src, (
        "resolver must use ${NGINX_RESOLVER} so podman-compose and k8s "
        "deployments can override the Docker-embedded DNS IP (127.0.0.11)."
    )


def test_nginx_default_resolver_is_docker_embedded_dns():
    """The Dockerfile must default NGINX_RESOLVER to 127.0.0.11 for docker-compose users."""
    df = _dockerfile()
    assert "NGINX_RESOLVER=127.0.0.11" in df, (
        "Dockerfile.frontend must set ENV NGINX_RESOLVER=127.0.0.11 so the default "
        "behaviour for docker-compose users is unchanged after the templating refactor."
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
