# fleet_platform/middleware/request_context.py
"""ASGI middleware that binds a per-request correlation context (#1052).

For every inbound HTTP request this middleware:

1. Takes the client-supplied ``X-Request-ID`` header if present, otherwise
   generates a fresh 12-character hex id (48 bits of ``secrets`` entropy —
   collision-safe for any realistic request volume while staying short enough
   to read out loud on an incident call).
2. Binds ``request_id``, ``method`` and ``path`` into
   :mod:`structlog.contextvars` so every JSON log line emitted anywhere inside
   the request (routes, services, exception handlers) carries them.
3. Clears those keys again in a ``finally`` block so nothing leaks into the
   next request handled by the same worker/context.
4. Sets ``X-Request-ID`` on the response **only** when the client did not send
   one, so callers can correlate follow-up bug reports with server-side logs.

Bindings made before ``call_next`` are visible downstream because Starlette's
``BaseHTTPMiddleware`` runs the rest of the app as a child task that inherits
the current contextvars context at spawn time.

Registered in ``api.main.create_app`` before ``PrometheusMiddleware``; see
the middleware-order comment there.
"""

import secrets

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

_BOUND_KEYS = ("request_id", "method", "path")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request_id/method/path to structlog contextvars per request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        client_request_id = request.headers.get(REQUEST_ID_HEADER)
        # 12-char hex id: token_hex(n) yields 2n hex characters.
        request_id = client_request_id or secrets.token_hex(6)

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
            if not client_request_id:
                response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            structlog.contextvars.unbind_contextvars(*_BOUND_KEYS)
