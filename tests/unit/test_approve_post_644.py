"""Unit tests for the POST-only approval gate and confirmation page (#644).

A mutating GET on the emailed link let mail-client/link-unfurler prefetch
auto-approve a destructive action. approve/reject are now POST-only and the
emailed link points to a side-effect-free GET confirmation page.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fleet_platform.api.routes.node_actions import _confirm_html, actions_router
from fleet_platform.models.pending_action import PendingAction


def _route_methods(path_suffix: str) -> set[str]:
    methods: set[str] = set()
    for route in actions_router.routes:
        if getattr(route, "path", "").endswith(path_suffix):
            methods |= set(getattr(route, "methods", set()) or set())
    return methods


def test_approve_is_post_only_not_get():
    methods = _route_methods("/{token}/approve")
    assert "POST" in methods
    assert "GET" not in methods


def test_reject_is_post_only_not_get():
    methods = _route_methods("/{token}/reject")
    assert "POST" in methods
    assert "GET" not in methods


def test_confirmation_page_is_get():
    methods = _route_methods("/{token}")
    assert "GET" in methods
    assert "POST" not in methods


def _action(status: str = "pending", *, expired: bool = False) -> PendingAction:
    now = datetime.now(UTC)
    return PendingAction(
        id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        action_type="process_stop",
        params='{"pid": 1, "name": "python"}',
        status=status,
        requested_by="alice",
        approval_token="tok123",
        created_at=now,
        expires_at=now + timedelta(minutes=-1 if expired else 15),
    )


def test_confirm_page_pending_renders_post_forms():
    html = _confirm_html(_action(), "tok123")
    # Buttons must submit via POST, never GET.
    assert 'method="post"' in html
    assert "/api/v1/actions/tok123/approve" in html
    assert "/api/v1/actions/tok123/reject" in html
    assert "Approve" in html and "Reject" in html


def test_confirm_page_expired_shows_no_buttons():
    html = _confirm_html(_action(expired=True), "tok123")
    assert "expired" in html.lower()
    assert 'method="post"' not in html


def test_confirm_page_settled_shows_status_no_buttons():
    html = _confirm_html(_action(status="executing"), "tok123")
    assert "executing" in html
    assert 'method="post"' not in html


def test_confirm_page_missing_action_is_safe():
    html = _confirm_html(None, "tok123")
    assert "not found" in html.lower()
    assert 'method="post"' not in html


def test_confirm_page_escapes_fields():
    a = _action()
    a.requested_by = "<script>alert(1)</script>"
    html = _confirm_html(a, "tok123")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
