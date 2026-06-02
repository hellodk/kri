"""Tests for the backend connectivity-probe endpoint (#362)."""
from fleet_platform.api.routes.platform_settings import _build_probe_url


def test_build_probe_url_full_http_url_unchanged():
    assert _build_probe_url("http://x.local/api", None) == "http://x.local/api"


def test_build_probe_url_https_unchanged():
    assert _build_probe_url("https://sonar.local", None) == "https://sonar.local"


def test_build_probe_url_host_with_port():
    assert _build_probe_url("100.89.50.27", 8080) == "http://100.89.50.27:8080"


def test_build_probe_url_bare_host_no_port():
    assert _build_probe_url("salt.fleet.local", None) == "http://salt.fleet.local"


def test_build_probe_url_strips_whitespace():
    assert _build_probe_url("  100.89.50.27  ", 8080) == "http://100.89.50.27:8080"


def test_endpoint_registered():
    from fleet_platform.api.routes.platform_settings import router

    paths = {r.path for r in router.routes}
    assert "/api/v1/settings/check-connectivity" in paths
