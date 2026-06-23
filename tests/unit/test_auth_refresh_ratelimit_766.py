"""Unit tests for #766 — rate-limit the auth/refresh endpoint.

Verifies that:
1. The `/auth/refresh` route handler carries a @limiter.limit decorator.
2. The route function signature accepts a `Request` argument (required by SlowAPI).
3. The limit matches the login endpoint (10/minute).
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "auth.py"


def test_auth_source_has_refresh_rate_limit():
    """auth.py must contain @limiter.limit(...) immediately before def refresh."""
    source = SOURCE.read_text()
    # Find the refresh definition block and check it has a limiter.limit line right before it
    assert "@limiter.limit" in source, "auth.py must import and use limiter.limit"
    # At least one @limiter.limit block must be associated with refresh
    assert re.search(r"@limiter\.limit\(.*\)\s*\nasync def refresh", source), (
        "@limiter.limit() decorator must appear directly before 'async def refresh'"
    )


def test_refresh_rate_limit_is_ten_per_minute():
    """The refresh endpoint rate limit should match login: 10/minute."""
    source = SOURCE.read_text()
    match = re.search(r'@limiter\.limit\("([^"]+)"\)\s*\nasync def refresh', source)
    assert match, 'Could not find @limiter.limit("...") before async def refresh'
    assert match.group(1) == "10/minute", f"Expected 10/minute rate limit on refresh, got: {match.group(1)!r}"


def test_refresh_handler_accepts_request():
    """SlowAPI requires the handler to accept a `Request` parameter."""
    source = SOURCE.read_text()
    # Find refresh function body and look for `request: Request` parameter
    match = re.search(r"async def refresh\s*\((.*?)\)\s*:", source, re.DOTALL)
    assert match, "Could not locate 'async def refresh(...):' in auth.py"
    params = match.group(1)
    assert "request" in params, "refresh() must accept a 'request: Request' parameter for SlowAPI rate limiting"


def test_refresh_route_accessible():
    """The /auth/refresh route must be importable and present in the router."""
    from fleet_platform.api.routes.auth import router

    paths = [getattr(r, "path", "") for r in router.routes]
    assert any(p.endswith("/refresh") for p in paths), f"POST /auth/refresh route not found in router; routes: {paths}"
