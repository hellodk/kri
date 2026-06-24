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
from starlette.requests import Request


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


limiter = Limiter(key_func=_default_key)
