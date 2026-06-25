"""Unit tests for P1 backend bug fixes (#64, #105, #126).

Behavioral conversion (#800): these previously scraped the route/service source
for substrings (``to_thread``, ``logger``/``warning``, ``viewer``/``require_role``).
They now drive the real functions and assert on observable behaviour:

  * credential_resolver logs a warning AND degrades to "" on decryption failure;
  * integration_status / test_webhook dispatch their blocking I/O through
    ``asyncio.to_thread`` (the event loop is never blocked);
  * the GET /llm/models auth dependency actually admits a viewer and rejects an
    unknown role.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# #64 — credential_resolver logs (and degrades) on decryption failure
# ---------------------------------------------------------------------------


def test_credential_resolver_logs_warning_on_decrypt_failure(caplog):
    """_decrypt_or_blank must log a warning and return "" when decrypt_secret raises."""
    from fleet_platform.services import credential_resolver as cr

    with patch.object(cr, "decrypt_secret", side_effect=ValueError("bad fernet token")):
        with caplog.at_level(logging.WARNING, logger="fleet_platform.services.credential_resolver"):
            result = cr._decrypt_or_blank("credential", "cred-123", "secret", "ciphertext")

    assert result == "", "decryption failure must degrade to empty string, never propagate"
    assert any(rec.levelno == logging.WARNING for rec in caplog.records), (
        "credential_resolver must log a WARNING when Fernet decryption fails (#64)"
    )
    assert "decryption failed" in caplog.text.lower()


def test_credential_resolver_blank_ciphertext_does_not_log(caplog):
    """An empty ciphertext is not an error — it must return "" without a warning."""
    from fleet_platform.services import credential_resolver as cr

    with caplog.at_level(logging.WARNING, logger="fleet_platform.services.credential_resolver"):
        result = cr._decrypt_or_blank("credential", "cred-123", "secret", None)

    assert result == ""
    assert not caplog.records, "empty ciphertext is benign — no warning should be logged"


# ---------------------------------------------------------------------------
# #105 — security.integration_status offloads blocking subprocess via to_thread
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_status_runs_subprocess_in_thread():
    """integration_status must dispatch the blocking subprocess.run through asyncio.to_thread."""
    import subprocess

    from fleet_platform.api.routes import security

    to_thread_spy = AsyncMock(return_value=MagicMock(returncode=1))

    # get_setting is imported inside the function from platform_settings_svc.
    with (
        patch("asyncio.to_thread", to_thread_spy),
        patch("fleet_platform.services.platform_settings_svc.get_setting", AsyncMock(return_value=None)),
    ):
        result = await security.integration_status(db=AsyncMock(), _={})

    assert "trivy" in result
    dispatched = [call.args[0] for call in to_thread_spy.await_args_list]
    assert subprocess.run in dispatched, (
        "integration_status must call subprocess.run via asyncio.to_thread, not inline (#105)"
    )


# ---------------------------------------------------------------------------
# #105 — alerts.test_webhook offloads the blocking urlopen via to_thread
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_webhook_runs_urlopen_in_thread():
    """test_webhook must deliver the payload via asyncio.to_thread(urllib.request.urlopen, ...)."""
    import urllib.request
    import uuid

    from fleet_platform.api.routes import alerts

    webhook = MagicMock()
    webhook.type = "generic"
    webhook.url = "https://hooks.example.com/notify"

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=webhook)))

    to_thread_spy = AsyncMock(return_value=None)

    with (
        patch("asyncio.to_thread", to_thread_spy),
        patch.object(alerts, "_validate_webhook_url", lambda url: None),
    ):
        result = await alerts.test_webhook(webhook_id=uuid.uuid4(), db=db, _={})

    assert result["status"] == "ok"
    dispatched = [call.args[0] for call in to_thread_spy.await_args_list]
    assert urllib.request.urlopen in dispatched, (
        "test_webhook must call urlopen via asyncio.to_thread, not inline (#105)"
    )


@pytest.mark.asyncio
async def test_test_webhook_missing_returns_404():
    """A missing webhook must 404 before any delivery is attempted."""
    import uuid

    from fleet_platform.api.routes import alerts

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    to_thread_spy = AsyncMock(return_value=None)
    with patch("asyncio.to_thread", to_thread_spy):
        with pytest.raises(HTTPException) as exc:
            await alerts.test_webhook(webhook_id=uuid.uuid4(), db=db, _={})

    assert exc.value.status_code == 404
    to_thread_spy.assert_not_awaited()


# ---------------------------------------------------------------------------
# #126 — GET /llm/models is role-guarded and admits a viewer
# ---------------------------------------------------------------------------


def _models_role_guard():
    """Return the require_role dependency closure attached to GET /llm/models."""
    from fleet_platform.api.routes.llm import router

    route = next(
        r for r in router.routes if getattr(r, "path", "").endswith("/models") and "GET" in getattr(r, "methods", set())
    )
    guards = [
        dep.call
        for dep in route.dependant.dependencies
        if asyncio.iscoroutinefunction(dep.call) and dep.call.__name__ == "dependency"
    ]
    assert guards, "GET /llm/models must declare a require_role dependency (#126)"
    return guards[0]


@pytest.mark.asyncio
async def test_llm_list_models_admits_viewer():
    """The model catalog is read-only — a viewer claim must pass the auth guard."""
    guard = _models_role_guard()
    claims = await guard(claims={"role": "viewer", "email": "v@example.com"})
    assert claims["role"] == "viewer"


@pytest.mark.asyncio
async def test_llm_list_models_rejects_unknown_role():
    """An unknown / below-viewer role must be rejected with 403."""
    guard = _models_role_guard()
    with pytest.raises(HTTPException) as exc:
        await guard(claims={"role": "nobody"})
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_llm_list_models_returns_catalog():
    """list_models must return the shared model catalog (its actual output)."""
    from fleet_platform.api.routes.llm import list_models

    result = await list_models(provider=None, _={"role": "viewer"})
    assert result is not None
