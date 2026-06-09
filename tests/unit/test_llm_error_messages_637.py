# tests/unit/test_llm_error_messages_637.py
"""
Tests for #637 Fix 2 — meaningful LLM error messages from _describe_http_error.
"""

import httpx

from fleet_platform.services.llm_caller import _describe_http_error


def _make_http_status_error(status: int, body: str, url: str = "http://h:1") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", url)
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_404_includes_response_body():
    exc = _make_http_status_error(
        404,
        '{"error":{"message":"No instance found for model X"}}',
    )
    msg = _describe_http_error(exc, "http://h:1")
    assert "No instance found for model X" in msg


def test_404_includes_settings_hint():
    exc = _make_http_status_error(404, '{"error":{"message":"No instance found for model X"}}')
    msg = _describe_http_error(exc, "http://h:1")
    assert "Settings → LLM" in msg


def test_404_includes_status_code():
    exc = _make_http_status_error(404, "not found")
    msg = _describe_http_error(exc, "http://h:1")
    assert "HTTP 404" in msg


def test_401_includes_auth_hint():
    exc = _make_http_status_error(401, "Unauthorized")
    msg = _describe_http_error(exc, "http://h:1")
    assert "authentication failed" in msg
    assert "Settings → LLM" in msg


def test_403_includes_auth_hint():
    exc = _make_http_status_error(403, "Forbidden")
    msg = _describe_http_error(exc, "http://h:1")
    assert "authentication failed" in msg


def test_500_no_extra_hint():
    exc = _make_http_status_error(500, "internal error")
    msg = _describe_http_error(exc, "http://h:1")
    assert "HTTP 500" in msg
    assert "internal error" in msg
    # No specific hint for 500
    assert "Settings" not in msg


def test_body_truncated_at_300_chars():
    long_body = "x" * 500
    exc = _make_http_status_error(500, long_body)
    msg = _describe_http_error(exc, "http://h:1")
    # Body in message must not exceed 300 chars
    # The full msg is "HTTP 500 from ...: <body>" — check body portion length
    body_part = msg.split(": ", 1)[1] if ": " in msg else ""
    assert len(body_part) <= 300
