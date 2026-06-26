"""Tests for #173: structured API error responses."""

from fleet_platform.core.errors import AppError, ErrorCode, error_code_for_status


def test_error_code_enum_values():
    assert ErrorCode.NOT_FOUND == "NOT_FOUND"
    assert ErrorCode.UNAUTHORIZED == "UNAUTHORIZED"
    assert ErrorCode.FORBIDDEN == "FORBIDDEN"


def test_error_code_for_status_known():
    assert error_code_for_status(404) == "NOT_FOUND"
    assert error_code_for_status(401) == "UNAUTHORIZED"
    assert error_code_for_status(403) == "FORBIDDEN"
    assert error_code_for_status(400) == "BAD_REQUEST"
    assert error_code_for_status(409) == "CONFLICT"
    assert error_code_for_status(422) == "UNPROCESSABLE"
    assert error_code_for_status(429) == "RATE_LIMITED"
    assert error_code_for_status(500) == "INTERNAL_ERROR"


def test_error_code_for_status_unknown_falls_back():
    assert error_code_for_status(418) == "INTERNAL_ERROR"


def test_app_error_stores_error_code():
    err = AppError(status_code=404, error_code="NODE_NOT_FOUND", detail="Node not found")
    assert err.status_code == 404
    assert err.error_code == "NODE_NOT_FOUND"
    assert err.detail == "Node not found"


def test_app_error_is_http_exception():
    from fastapi import HTTPException

    err = AppError(status_code=404, error_code="NOT_FOUND", detail="nope")
    assert isinstance(err, HTTPException)


def test_main_registers_http_exception_handler():
    """The app must register the structured HTTP exception handler for HTTPException (#173)."""
    from fastapi import HTTPException

    from fleet_platform.api.main import create_app
    from fleet_platform.core.errors import AppError

    app = create_app()
    assert HTTPException in app.exception_handlers, (
        "main.py must register a handler for HTTPException to return structured {error_code, detail} responses"
    )
    handler = app.exception_handlers[HTTPException]
    assert callable(handler), "The registered HTTPException handler must be callable"

    # Verify the handler returns an error_code field (as AppError is a subclass of HTTPException)
    import asyncio
    from unittest.mock import MagicMock

    request = MagicMock()
    exc = AppError(status_code=404, error_code="NODE_NOT_FOUND", detail="not found")
    response = asyncio.run(handler(request, exc))
    body = response.body
    assert b"error_code" in body, "The handler must include 'error_code' in the JSON response body"
