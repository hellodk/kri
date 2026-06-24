"""Metrics endpoint authentication helpers (#763).

The /metrics endpoint must not be unauthenticated at the application layer.
Two authentication paths are supported:

  1. Metrics token — a static shared secret configured via METRICS_TOKEN.
     Prometheus scrape jobs should use:
       scrape_configs:
         - job_name: kri
           authorization:
             credentials: <METRICS_TOKEN value>
     This is the recommended path for automated scraping.

  2. Bearer JWT — any valid kri access token (any role).
     Useful for debugging / ad-hoc queries from authenticated users.

If METRICS_TOKEN is unset *and* no valid JWT is presented, the endpoint
returns 401 Unauthorized.
"""

from fastapi import HTTPException, status

from fleet_platform.core.auth import TokenExpiredError, TokenInvalidError, decode_token


def verify_metrics_request(request, *, metrics_token: str | None) -> None:
    """Verify that the incoming request is authorised to scrape /metrics.

    Raises HTTPException(401) on failure.  Returns None on success.
    """
    auth_header: str = (
        getattr(request.headers, "get", lambda k, d=None: request.headers.get(k, d))("Authorization", "") or ""
    )

    scheme, _, credential = auth_header.partition(" ")
    credential = credential.strip()

    if scheme.lower() != "bearer" or not credential:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Path 1: static metrics token
    if metrics_token and credential == metrics_token:
        return

    # Path 2: valid JWT (any role)
    try:
        decode_token(credential)
        return
    except (TokenExpiredError, TokenInvalidError):
        pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials for /metrics",
        headers={"WWW-Authenticate": "Bearer"},
    )
