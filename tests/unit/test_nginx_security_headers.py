"""Unit tests for #128 — nginx security headers."""

from pathlib import Path

NGINX_CONF = Path("deploy/nginx.conf.template")


def _conf():
    return NGINX_CONF.read_text()


def test_nginx_has_x_content_type_options():
    assert "X-Content-Type-Options" in _conf(), "nginx must set X-Content-Type-Options"


def test_nginx_has_x_frame_options():
    assert "X-Frame-Options" in _conf(), "nginx must set X-Frame-Options to prevent clickjacking"


def test_nginx_has_xss_protection():
    assert "X-XSS-Protection" in _conf(), "nginx must set X-XSS-Protection"


def test_nginx_has_referrer_policy():
    assert "Referrer-Policy" in _conf(), "nginx must set Referrer-Policy"


def test_nginx_no_hsts_on_http():
    """HSTS must not be set — service runs over plain HTTP."""
    assert "Strict-Transport-Security" not in _conf(), (
        "nginx must not set HSTS when serving over plain HTTP — breaks browser HTTPS redirect loops"
    )
