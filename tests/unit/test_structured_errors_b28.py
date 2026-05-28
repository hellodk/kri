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
    from pathlib import Path
    src = (Path(__file__).parent.parent.parent / "fleet_platform/api/main.py").read_text()
    assert "structured_http_exception_handler" in src
    assert "error_code" in src
    assert "AppError" in src
