"""Application-layer security header middleware.

Adds security headers to every response. Registered in main.py after
PrometheusMiddleware so it runs on all responses.

Headers set:
  Content-Security-Policy  — restricts resource origins (#764)
  X-Frame-Options          — belt-and-suspenders clickjacking guard
  X-Content-Type-Options   — stops MIME-sniffing

Headers intentionally NOT set:
  X-XSS-Protection — deprecated (removed from modern browsers; the CSP
    policy above supersedes it). Browsers that still honour X-XSS-Protection
    can mis-fire on legitimate pages, causing silent content blocking.
    RFC / ADR note: the API follows the /api/v1/ prefix convention established
    at launch; no versioning change is needed alongside this header removal.
    (#755)
  Strict-Transport-Security — the API may run behind a TLS-terminating
    reverse proxy; setting HSTS at the application layer is wrong here.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Conservative CSP that works with a React SPA served separately.
# Scripts / styles need 'unsafe-inline' because React's production bundles
# include inline chunks. Tighten to nonce-based CSP once the frontend
# migrates to a nonce-capable build toolchain.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Remove X-XSS-Protection if a lower-level handler added it (#755).
        # MutableHeaders does not expose .pop(); use del inside a guard.
        if "X-XSS-Protection" in response.headers:
            del response.headers["X-XSS-Protection"]
        return response
