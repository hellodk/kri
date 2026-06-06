"""#419: nginx must proxy /metrics to the API (restricted to private nets) so kri
metrics are scrapeable in every deploy mode — not swallowed by the SPA fallback."""

from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
CONFS = [ROOT / "deploy/nginx.conf", ROOT / "deploy/nginx-tls.conf"]


def test_both_nginx_confs_route_metrics_to_api():
    for conf in CONFS:
        text = conf.read_text()
        assert "location = /metrics" in text, f"{conf.name}: no /metrics location"
        # the /metrics block must proxy to the api upstream, not fall through to the SPA
        block = text.split("location = /metrics", 1)[1].split("location /", 1)[0]
        assert "proxy_pass" in block and "api:8000" in block, f"{conf.name}: /metrics not proxied to api"


def test_metrics_route_is_access_restricted():
    for conf in CONFS:
        block = conf.read_text().split("location = /metrics", 1)[1].split("}", 1)[0]
        assert "deny all" in block, f"{conf.name}: /metrics not restricted (deny all missing)"
        assert "100.64.0.0/10" in block, f"{conf.name}: Tailscale range not allowed"
