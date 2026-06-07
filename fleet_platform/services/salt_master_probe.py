"""SaltMasterProbe — prerequisite validation service for a SaltMaster row.

Returns structured per-check results without raising.  All network I/O is
synchronous (socket + requests) to keep the implementation simple and testable.
The caller must run this in a thread-pool executor if called from async context.

NOTE: This probe runs from the WORKER container (control-plane reachability).
It is intentionally NOT a substitute for node-vantage reachability — whether a
minion can reach the master on 4505/4506 is validated at bootstrap time via
nc(1) checks in playbooks/bootstrap_mac_mini.yml (see #536, epic #537).

Issue #517, epic #523.
"""

import socket
import time
from typing import Any, TypedDict

import requests

from fleet_platform.models.salt_master import SaltMaster

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

StatusLiteral = str  # "pass" | "warn" | "fail"
AggregateLiteral = str  # "unknown" | "healthy" | "degraded" | "unreachable"


class CheckResult(TypedDict):
    check: str
    status: StatusLiteral
    detail: str
    latency_ms: int


class ProbeResult(TypedDict):
    status: AggregateLiteral
    checks: list[CheckResult]


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

_CONNECT_TIMEOUT = 5  # seconds — short TCP probe timeout
_API_TIMEOUT = 10  # seconds — salt-api HTTP timeout


def _ms(start: float) -> int:
    """Elapsed milliseconds since a monotonic start time."""
    return int((time.monotonic() - start) * 1000)


def _check_dns(address: str) -> CheckResult:
    start = time.monotonic()
    try:
        socket.getaddrinfo(address, None)
        return CheckResult(
            check="dns",
            status="pass",
            detail=f"{address!r} resolves",
            latency_ms=_ms(start),
        )
    except socket.gaierror as exc:
        return CheckResult(
            check="dns",
            status="fail",
            detail=f"DNS resolution failed for {address!r}: {exc}",
            latency_ms=_ms(start),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            check="dns",
            status="fail",
            detail=f"Unexpected error resolving {address!r}: {exc}",
            latency_ms=_ms(start),
        )


def _check_tcp(address: str, port: int, check_name: str) -> CheckResult:
    start = time.monotonic()
    try:
        with socket.create_connection((address, port), timeout=_CONNECT_TIMEOUT):
            pass
        return CheckResult(
            check=check_name,
            status="pass",
            detail=f"TCP {address}:{port} reachable",
            latency_ms=_ms(start),
        )
    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        return CheckResult(
            check=check_name,
            status="fail",
            detail=f"TCP {address}:{port} unreachable: {exc}",
            latency_ms=_ms(start),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            check=check_name,
            status="fail",
            detail=f"Unexpected error connecting to {address}:{port}: {exc}",
            latency_ms=_ms(start),
        )


def _check_salt_api_auth(
    api_url: str, api_user: str, api_password: str, api_eauth: str, tls_verify: bool = False
) -> CheckResult:
    """POST to salt-api /run with auth params; pass if 200 + token returned."""
    start = time.monotonic()
    try:
        payload: list[dict[str, Any]] = [
            {
                "client": "runner",
                "fun": "test.ping",
                "username": api_user,
                "password": api_password,
                "eauth": api_eauth,
            }
        ]
        resp = requests.post(
            f"{api_url}/run",
            json=payload,
            timeout=_API_TIMEOUT,
            verify=tls_verify,
        )
        if resp.status_code == 401:
            return CheckResult(
                check="salt_api_auth",
                status="fail",
                detail="salt-api authentication failed (401 Unauthorized)",
                latency_ms=_ms(start),
            )
        if resp.status_code == 403:
            return CheckResult(
                check="salt_api_auth",
                status="fail",
                detail="salt-api authentication failed (403 Forbidden)",
                latency_ms=_ms(start),
            )
        resp.raise_for_status()
        return CheckResult(
            check="salt_api_auth",
            status="pass",
            detail=f"salt-api auth succeeded (HTTP {resp.status_code})",
            latency_ms=_ms(start),
        )
    except requests.ConnectionError as exc:
        return CheckResult(
            check="salt_api_auth",
            status="fail",
            detail=f"Cannot reach salt-api at {api_url}: {exc}",
            latency_ms=_ms(start),
        )
    except requests.HTTPError as exc:
        return CheckResult(
            check="salt_api_auth",
            status="fail",
            detail=f"salt-api HTTP error: {exc}",
            latency_ms=_ms(start),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            check="salt_api_auth",
            status="fail",
            detail=f"salt-api auth unexpected error: {exc}",
            latency_ms=_ms(start),
        )


def _check_key_store(
    api_url: str, api_user: str, api_password: str, api_eauth: str, tls_verify: bool = False
) -> CheckResult:
    """Run key.list_all via runner; distinguish permission errors from empty results."""
    start = time.monotonic()
    try:
        payload: list[dict[str, Any]] = [
            {
                "client": "runner",
                "fun": "key.list_all",
                "username": api_user,
                "password": api_password,
                "eauth": api_eauth,
            }
        ]
        resp = requests.post(
            f"{api_url}/run",
            json=payload,
            timeout=_API_TIMEOUT,
            verify=tls_verify,
        )
        if resp.status_code in (401, 403):
            return CheckResult(
                check="key_store",
                status="fail",
                detail="cannot read keys (permission)",
                latency_ms=_ms(start),
            )
        resp.raise_for_status()
        data = resp.json()
        # Salt permission/access errors surface as strings inside the return list
        returns = data.get("return", [])
        if returns and isinstance(returns[0], str):
            raw = returns[0].lower()
            if "permission" in raw or "access denied" in raw or "authentication" in raw:
                return CheckResult(
                    check="key_store",
                    status="fail",
                    detail="cannot read keys (permission)",
                    latency_ms=_ms(start),
                )
        return CheckResult(
            check="key_store",
            status="pass",
            detail="key store readable",
            latency_ms=_ms(start),
        )
    except requests.HTTPError as exc:
        return CheckResult(
            check="key_store",
            status="fail",
            detail=f"key_store HTTP error: {exc}",
            latency_ms=_ms(start),
        )
    except requests.ConnectionError as exc:
        return CheckResult(
            check="key_store",
            status="fail",
            detail=f"key_store connection error: {exc}",
            latency_ms=_ms(start),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            check="key_store",
            status="fail",
            detail=f"key_store unexpected error: {exc}",
            latency_ms=_ms(start),
        )


def _check_version(
    api_url: str, api_user: str, api_password: str, api_eauth: str, tls_verify: bool = False
) -> CheckResult:
    start = time.monotonic()
    try:
        payload: list[dict[str, Any]] = [
            {
                "client": "runner",
                "fun": "manage.versions",
                "username": api_user,
                "password": api_password,
                "eauth": api_eauth,
            }
        ]
        resp = requests.post(
            f"{api_url}/run",
            json=payload,
            timeout=_API_TIMEOUT,
            verify=tls_verify,
        )
        resp.raise_for_status()
        data = resp.json()
        returns = data.get("return", [{}])
        result = returns[0] if returns else {}
        if isinstance(result, dict) and result.get("up_to_date") is False:
            return CheckResult(
                check="version",
                status="warn",
                detail=f"Version mismatch detected: {result}",
                latency_ms=_ms(start),
            )
        return CheckResult(
            check="version",
            status="pass",
            detail="versions consistent",
            latency_ms=_ms(start),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            check="version",
            status="warn",
            detail=f"manage.versions unavailable: {exc}",
            latency_ms=_ms(start),
        )


def _check_minions_up(
    api_url: str, api_user: str, api_password: str, api_eauth: str, tls_verify: bool = False
) -> CheckResult:
    start = time.monotonic()
    try:
        payload: list[dict[str, Any]] = [
            {
                "client": "runner",
                "fun": "manage.up",
                "username": api_user,
                "password": api_password,
                "eauth": api_eauth,
            }
        ]
        resp = requests.post(
            f"{api_url}/run",
            json=payload,
            timeout=_API_TIMEOUT,
            verify=tls_verify,
        )
        resp.raise_for_status()
        data = resp.json()
        returns = data.get("return", [[]])
        minions = returns[0] if returns else []
        count = len(minions) if isinstance(minions, list) else 0
        return CheckResult(
            check="minions_up",
            status="pass",
            detail=f"{count} minion(s) up",
            latency_ms=_ms(start),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            check="minions_up",
            status="warn",
            detail=f"manage.up unavailable: {exc}",
            latency_ms=_ms(start),
        )


def _check_token_delivery(master: SaltMaster) -> CheckResult:
    """For ingest mode check that api_url is configured; pass for direct mode."""
    start = time.monotonic()
    if master.token_delivery != "ingest":
        return CheckResult(
            check="token_delivery",
            status="pass",
            detail=f"token_delivery={master.token_delivery!r} — no ingest check required",
            latency_ms=_ms(start),
        )
    # ingest mode: api_url must be configured
    if not master.api_url:
        return CheckResult(
            check="token_delivery",
            status="warn",
            detail="token_delivery=ingest but api_url is not configured",
            latency_ms=_ms(start),
        )
    return CheckResult(
        check="token_delivery",
        status="pass",
        detail=f"token_delivery=ingest, api_url configured ({master.api_url!r})",
        latency_ms=_ms(start),
    )


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def _aggregate(checks: list[CheckResult]) -> AggregateLiteral:
    statuses = {c["check"]: c["status"] for c in checks}
    if statuses.get("salt_api_auth") == "fail":
        return "unreachable"
    if any(c["status"] == "fail" for c in checks):
        return "degraded"
    if all(c["status"] == "pass" for c in checks):
        return "healthy"
    # mix of pass + warn
    return "degraded"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_probe(master: SaltMaster) -> ProbeResult:
    """Validate a salt-master's prerequisites and return structured results.

    This is an async function but all network I/O inside is synchronous
    (requests + socket).  For production use wrap in asyncio.to_thread or
    anyio.to_thread.run_sync when calling from the FastAPI handler.

    No check may raise — all exceptions are caught and returned as fail/warn.
    """
    from fleet_platform.services.platform_settings_svc import decrypt_secret

    # Decrypt the API password once
    api_password: str = ""
    if master.api_password_enc:
        try:
            api_password = decrypt_secret(master.api_password_enc)
        except Exception as exc:  # noqa: BLE001
            # Return immediately — can't do anything without credentials
            return ProbeResult(
                status="unreachable",
                checks=[
                    CheckResult(
                        check="salt_api_auth",
                        status="fail",
                        detail=f"Cannot decrypt api_password_enc: {exc}",
                        latency_ms=0,
                    )
                ],
            )

    api_url: str = master.api_url or ""
    api_user: str = master.api_user or ""
    api_eauth: str = master.api_eauth or "pam"
    tls_verify: bool = getattr(master, "tls_verify", False)

    checks: list[CheckResult] = []

    # 1. DNS
    checks.append(_check_dns(master.address))

    # 2. TCP port checks
    checks.append(_check_tcp(master.address, master.publish_port, "tcp_4505"))
    checks.append(_check_tcp(master.address, master.ret_port, "tcp_4506"))

    # 3. salt-api auth
    if api_url and api_user:
        auth_result = _check_salt_api_auth(api_url, api_user, api_password, api_eauth, tls_verify=tls_verify)
    else:
        auth_result = CheckResult(
            check="salt_api_auth",
            status="fail",
            detail="api_url or api_user not configured",
            latency_ms=0,
        )
    checks.append(auth_result)

    # Short-circuit if auth failed — no point running runner checks
    if auth_result["status"] == "fail":
        checks.append(
            CheckResult(
                check="key_store",
                status="fail",
                detail="skipped — salt_api_auth failed",
                latency_ms=0,
            )
        )
        checks.append(
            CheckResult(
                check="version",
                status="warn",
                detail="skipped — salt_api_auth failed",
                latency_ms=0,
            )
        )
        checks.append(
            CheckResult(
                check="minions_up",
                status="warn",
                detail="skipped — salt_api_auth failed",
                latency_ms=0,
            )
        )
    else:
        checks.append(_check_key_store(api_url, api_user, api_password, api_eauth, tls_verify=tls_verify))
        checks.append(_check_version(api_url, api_user, api_password, api_eauth, tls_verify=tls_verify))
        checks.append(_check_minions_up(api_url, api_user, api_password, api_eauth, tls_verify=tls_verify))

    # 7. Token delivery
    checks.append(_check_token_delivery(master))

    aggregate = _aggregate(checks)
    return ProbeResult(status=aggregate, checks=checks)
