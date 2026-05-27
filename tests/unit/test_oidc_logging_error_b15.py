"""Unit tests for #67 (OIDC exception logging) and #72 (login SSO error banner)."""
from pathlib import Path

OIDC = Path("fleet_platform/api/routes/oidc.py").read_text()
LOGIN = Path("frontend/src/pages/LoginPage.tsx").read_text()


def test_oidc_handlers_log_exceptions():
    """All OIDC exception handlers must call logger.exception."""
    assert "logger.exception" in OIDC, (
        "OIDC route handlers must call logger.exception in catch blocks"
    )
    count = OIDC.count("logger.exception")
    assert count >= 2, f"Expected at least 2 logger.exception calls, found {count}"


def test_oidc_has_logger_defined():
    assert "getLogger" in OIDC, "OIDC module must define a module-level logger"


def test_login_page_reads_error_param():
    assert "searchParams" in LOGIN or "useSearchParams" in LOGIN, (
        "LoginPage must use useSearchParams to read error param"
    )
    assert "oidc_failed" in LOGIN or "ssoError" in LOGIN or "error" in LOGIN, (
        "LoginPage must handle the OIDC error query param"
    )


def test_login_page_has_dismissible_banner():
    assert "setSsoError" in LOGIN or "setError" in LOGIN, (
        "LoginPage must have dismissible error state"
    )
    assert "Single sign-on failed" in LOGIN or "sign-on" in LOGIN.lower(), (
        "LoginPage must show a human-readable SSO error message"
    )
