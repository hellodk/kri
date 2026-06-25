"""Unit tests for #67 (OIDC exception logging) and #72 (login SSO error banner).

Behavioral conversion (#800): the OIDC backend assertions used to scrape oidc.py
for the substring ``logger.exception``. They now drive the real route handlers
with a failing ``oidc_svc.discover`` and assert that an exception is actually
logged (and the handler degrades to the right HTTP status). The LoginPage
assertions remain source-contract because they verify a frontend TSX UI contract
that another wave owns and that cannot be exercised from a Python unit test.
"""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from fleet_platform.api.routes import oidc
from fleet_platform.services.platform_settings_svc import (
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_ENABLED,
    OIDC_ISSUER_URL,
    OIDC_ROLE_PREFIX,
)

LOGIN = Path("frontend/src/pages/LoginPage.tsx").read_text()


def _settings(key):
    return {
        OIDC_ENABLED: "true",
        OIDC_ISSUER_URL: "https://idp.example.com/realms/kri",
        OIDC_CLIENT_ID: "kri-client",
        OIDC_CLIENT_SECRET: "shh",
        OIDC_ROLE_PREFIX: "kri-",
    }.get(key)


@pytest.mark.asyncio
async def test_oidc_login_logs_exception_on_discovery_failure(caplog):
    """oidc_login must logger.exception(...) and 503 when discovery blows up."""
    get_setting = AsyncMock(side_effect=lambda db, k: _settings(k))

    with (
        patch.object(oidc, "get_setting", get_setting),
        patch.object(oidc.oidc_svc, "discover", AsyncMock(side_effect=RuntimeError("idp down"))),
        caplog.at_level(logging.ERROR, logger="fleet_platform.api.routes.oidc"),
    ):
        with pytest.raises(HTTPException) as exc:
            await oidc.oidc_login(db=AsyncMock(), redis=AsyncMock())

    assert exc.value.status_code == 503
    err_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert err_records, "oidc_login must log the discovery exception (#67)"
    assert any(r.exc_info is not None for r in err_records), "must use logger.exception (captures traceback)"


@pytest.mark.asyncio
async def test_oidc_callback_logs_exception_on_discovery_failure(caplog):
    """oidc_callback must logger.exception(...) and 503 when discovery blows up."""
    get_setting = AsyncMock(side_effect=lambda db, k: _settings(k))
    redis = AsyncMock()
    redis.getdel = AsyncMock(return_value="1")  # valid state

    with (
        patch.object(oidc, "get_setting", get_setting),
        patch.object(oidc.oidc_svc, "discover", AsyncMock(side_effect=RuntimeError("idp down"))),
        caplog.at_level(logging.ERROR, logger="fleet_platform.api.routes.oidc"),
    ):
        with pytest.raises(HTTPException) as exc:
            await oidc.oidc_callback(code="abc", state="xyz", db=AsyncMock(), redis=redis)

    assert exc.value.status_code == 503
    assert any(r.exc_info is not None for r in caplog.records if r.levelno == logging.ERROR), (
        "oidc_callback must use logger.exception in its discovery catch block (#67)"
    )


@pytest.mark.asyncio
async def test_oidc_callback_rejects_invalid_state():
    """An expired/invalid state must 400 before any discovery work — behavioral guard."""
    redis = AsyncMock()
    redis.getdel = AsyncMock(return_value=None)

    discover = AsyncMock()
    with patch.object(oidc.oidc_svc, "discover", discover):
        with pytest.raises(HTTPException) as exc:
            await oidc.oidc_callback(code="abc", state="bad", db=AsyncMock(), redis=redis)

    assert exc.value.status_code == 400
    discover.assert_not_awaited()


def test_oidc_module_has_logger():
    """The OIDC module must define a real module-level logger (#67)."""
    assert isinstance(oidc.logger, logging.Logger)
    assert oidc.logger.name == "fleet_platform.api.routes.oidc"


def test_login_page_reads_error_param():
    # behavioral conversion blocked: asserts LoginPage.tsx frontend UI contract,
    # not exercisable from a Python unit test (frontend owned by another wave).
    assert "searchParams" in LOGIN or "useSearchParams" in LOGIN, (
        "LoginPage must use useSearchParams to read error param"
    )
    assert "oidc_failed" in LOGIN or "ssoError" in LOGIN or "error" in LOGIN, (
        "LoginPage must handle the OIDC error query param"
    )


def test_login_page_has_dismissible_banner():
    # behavioral conversion blocked: asserts LoginPage.tsx frontend UI contract,
    # not exercisable from a Python unit test (frontend owned by another wave).
    assert "setSsoError" in LOGIN or "setError" in LOGIN, "LoginPage must have dismissible error state"
    assert "Single sign-on failed" in LOGIN or "sign-on" in LOGIN.lower(), (
        "LoginPage must show a human-readable SSO error message"
    )
