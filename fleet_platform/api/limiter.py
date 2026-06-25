# fleet_platform/api/limiter.py
"""Centralised SlowAPI limiter instance.

Importing from this module (instead of from main.py) avoids the circular
import that arises when routes import `limiter` from `main.py`, which itself
imports the routes.

Rate-limiter key function (#759)
---------------------------------
The original ``get_remote_address`` from slowapi reads the leftmost
``X-Forwarded-For`` entry, which an attacker can trivially spoof to bypass
per-IP rate limits (e.g. flood logins from "different" IPs).

``make_real_ip_key(proxy_count)`` implements the trusted-proxy model:

  proxy_count = 0  (default)
      Use ``request.client.host`` — the actual TCP socket peer address.
      XFF is completely ignored; spoofing is impossible.

  proxy_count = N (N >= 1)
      There are N trusted reverse-proxy hops in front of the API.
      Each proxy appends the address it received the connection from to XFF:
        client → proxy1 → … → proxyN → API
        XFF seen by API:  "client_ip, proxy1_ip, …, proxy(N-1)_ip"
        request.client.host = proxyN_ip (trusted)

      The real client IP is at index ``len(xff_ips) - N`` in the XFF list
      (N entries from the right are trusted proxies; the one to the left
      of them is the attacker-inaccessible real client address).

      This is equivalent to Nginx's ``$realip_recursive`` with
      ``set_real_ip_from`` and means an attacker cannot inflate the XFF list
      to shift which entry we pick — the rightmost entries are always the
      ones inserted by trusted infrastructure.
"""

from typing import Callable

from slowapi import Limiter
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def make_real_ip_key(proxy_count: int) -> Callable[[Request], str]:
    """Return a rate-limiter key function for the given trusted-proxy count."""

    def _key(request: Request) -> str:
        if proxy_count == 0:
            return request.client.host if request.client else "127.0.0.1"

        xff: str = request.headers.get("X-Forwarded-For", "")
        ips = [ip.strip() for ip in xff.split(",") if ip.strip()]
        idx = len(ips) - proxy_count
        if 0 <= idx < len(ips):
            return ips[idx]
        return request.client.host if request.client else "127.0.0.1"

    return _key


def _default_key(request: Request) -> str:
    """Lazy key function that reads trusted_proxy_count from settings at call time.

    This avoids a circular import: limiter.py is imported before settings
    are fully wired.  The proxy_count is resolved on the first request.
    """
    from fleet_platform.core.config import settings

    return make_real_ip_key(settings.trusted_proxy_count)(request)


def _rate_limiting_enabled() -> bool:
    """Rate limiting is on everywhere except the automated E2E test stack.

    The Playwright suite (#905) drives many ``/auth/login`` calls from a single
    runner IP — the login/refresh/logout endpoint tests, the UI login journeys,
    and per-spec API logins for two seeded users. Even with the helper's 12-min
    token cache this legitimately exceeds the 10/min per-IP budget, and once the
    limit trips every downstream test cascades into 429-derived failures (empty
    token bodies → 401/403/422, and 30s ``beforeEach`` login timeouts). A real
    test deployment turns the limiter off the same way. Production and
    development keep it ENABLED — only ENVIRONMENT=test disables it, and this is
    resolved once at process start (the E2E api container sets ENVIRONMENT=test).
    """
    from fleet_platform.core.config import settings

    return settings.environment != "test"


limiter = Limiter(key_func=_default_key, enabled=_rate_limiting_enabled())


class RateLimitHeadersMiddleware:
    """Emit ``X-RateLimit-*`` headers on every HTTP response for rate-limited routes.

    SlowAPI's own header injection is not usable here:

    * ``Limiter(headers_enabled=True)`` makes the ``@limiter.limit`` *decorator*
      try to inject headers into the endpoint's return value. Our endpoints
      return plain dicts (not ``Response`` objects) and don't declare a
      ``response: Response`` parameter, so that path raises
      "parameter `response` must be an instance of Response" — it would break
      every decorated dict-returning route.
    * ``SlowAPIMiddleware`` deliberately *exempts* any route that carries a
      ``@limiter.limit`` decorator, so it never adds headers to e.g. ``/auth/login``.

    This is a pure-ASGI middleware (not ``BaseHTTPMiddleware``) so it leaves
    WebSocket scopes completely untouched — wrapping WebSocket routes in
    ``BaseHTTPMiddleware`` breaks their close-code handshake. For HTTP requests
    we read ``view_rate_limit`` from the shared scope state (the decorator sets
    it in ``_check_request_limit`` *before* the endpoint runs, so it is present
    even when the endpoint raises, e.g. a 401 login) and append the standard
    headers as the response starts, mirroring ``Limiter._inject_headers``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                current_limit = (scope.get("state") or {}).get("view_rate_limit")
                limiter_obj = getattr(getattr(scope.get("app"), "state", None), "limiter", None)
                if current_limit is not None and limiter_obj is not None:
                    try:
                        item, args = current_limit
                        window_stats = limiter_obj.limiter.get_window_stats(item, *args)
                        headers = MutableHeaders(scope=message)
                        headers["X-RateLimit-Limit"] = str(item.amount)
                        headers["X-RateLimit-Remaining"] = str(window_stats[1])
                        headers["X-RateLimit-Reset"] = str(1 + window_stats[0])
                    except Exception:  # never let header decoration break a response
                        pass
            await send(message)

        await self.app(scope, receive, send_wrapper)
