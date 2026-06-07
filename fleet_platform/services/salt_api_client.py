"""Reusable synchronous salt-api client — epic #523, issue #518.

Wraps salt-api /run endpoint for wheel and runner clients.
All I/O is synchronous (requests); callers running in async context
must use run_in_executor.
"""

from typing import Any

import requests

from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.services.platform_settings_svc import decrypt_secret

_API_TIMEOUT = 10  # seconds


class SaltApiError(Exception):
    """Raised when salt-api returns an error or is unreachable.

    Carries a human-readable ``reason`` string suitable for surfacing
    in API responses (e.g. as ``degraded_reason``).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _post(master: SaltMaster, lowstate: list[dict]) -> Any:
    """POST *lowstate* to ``master.api_url/run`` and return ``return[0]``.

    Injects ``username``, ``password``, and ``eauth`` into every lowstate item
    so the caller only needs to supply the client/fun/kwargs.

    Raises ``SaltApiError`` with a descriptive reason on:
    - HTTP 401 / 403 (auth failure)
    - ``requests.ConnectionError`` (unreachable)
    - ``requests.Timeout``
    - any other non-2xx HTTP status
    """
    api_url = (master.api_url or "").rstrip("/")
    api_user = master.api_user or ""
    api_eauth = master.api_eauth or "pam"

    try:
        api_password = decrypt_secret(master.api_password_enc) if master.api_password_enc else ""
    except Exception as exc:
        raise SaltApiError(f"Cannot decrypt salt-api password: {exc}") from exc

    # Inject credentials into every lowstate item
    enriched = [{**item, "username": api_user, "password": api_password, "eauth": api_eauth} for item in lowstate]

    tls_verify: bool = getattr(master, "tls_verify", False)

    try:
        resp = requests.post(f"{api_url}/run", json=enriched, timeout=_API_TIMEOUT, verify=tls_verify)
    except requests.ConnectionError as exc:
        raise SaltApiError(f"Cannot reach salt-api at {api_url}: {exc}") from exc
    except requests.Timeout:
        raise SaltApiError(f"salt-api request timed out after {_API_TIMEOUT}s") from None

    if resp.status_code == 401:
        raise SaltApiError("salt-api authentication failed (401 Unauthorized)")
    if resp.status_code == 403:
        raise SaltApiError("salt-api authentication failed (403 Forbidden)")

    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise SaltApiError(f"salt-api HTTP error: {exc}") from exc

    try:
        return resp.json()["return"][0]
    except (KeyError, IndexError, ValueError) as exc:
        raise SaltApiError(f"Unexpected salt-api response shape: {exc}") from exc


def run_wheel(master: SaltMaster, fun: str, **kwargs: Any) -> Any:
    """Call a salt wheel function via salt-api.

    ``fun`` examples: ``"key.list_all"``, ``"key.accept"``, ``"key.reject"``,
    ``"key.delete"``.  Extra keyword arguments are forwarded as lowstate fields
    (e.g. ``match=minion_id``).
    """
    return _post(master, [{"client": "wheel", "fun": fun, **kwargs}])


def run_runner(master: SaltMaster, fun: str, **kwargs: Any) -> Any:
    """Call a salt runner function via salt-api.

    ``fun`` examples: ``"test.ping"``, ``"manage.status"``.
    """
    return _post(master, [{"client": "runner", "fun": fun, **kwargs}])
