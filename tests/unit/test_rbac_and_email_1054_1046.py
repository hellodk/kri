"""Unit tests for #1045 (WebSocket RBAC) and #1046 item 5 (email escaping).

Covers three guards:
  1. ensure_ws_role — pure role guard shared by webssh.py and vnc.py WS handlers.
  2. validate_source_dir — playbook tree source_dir allow-list against approved roots.
  3. _build_approval_body — HTML escaping of interpolated values in approval emails.
"""

import pytest

# ── #1045: WebSocket role enforcement ─────────────────────────────────────────


def test_ensure_ws_role_viewer_denied():
    """viewer must NOT be able to open interactive WS sessions (#1045)."""
    from fleet_platform.api.routes.webssh import WsRoleDeniedError, ensure_ws_role

    with pytest.raises(WsRoleDeniedError):
        ensure_ws_role("viewer")


def test_ensure_ws_role_operator_allowed():
    from fleet_platform.api.routes.webssh import ensure_ws_role

    ensure_ws_role("operator")  # must not raise


def test_ensure_ws_role_admin_allowed():
    from fleet_platform.api.routes.webssh import ensure_ws_role

    ensure_ws_role("admin")  # must not raise


def test_ensure_ws_role_missing_or_unknown_denied():
    """Missing/unknown roles must never satisfy the requirement."""
    from fleet_platform.api.routes.webssh import WsRoleDeniedError, ensure_ws_role

    with pytest.raises(WsRoleDeniedError):
        ensure_ws_role(None)
    with pytest.raises(WsRoleDeniedError):
        ensure_ws_role("superuser")


def test_vnc_session_wires_the_guard():
    """vnc_session must call ensure_ws_role and close 4003 on denial (#1045)."""
    from fleet_platform.api.routes import vnc

    src = open(vnc.__file__).read()
    assert "ensure_ws_role" in src, "vnc_session must call ensure_ws_role"
    assert "code=4003" in src, "vnc_session must close with code=4003 on denial"


def test_webssh_session_wires_the_guard():
    """webssh_session must call ensure_ws_role and close 4003 on denial (#1045)."""
    from fleet_platform.api.routes import webssh

    src = open(webssh.__file__).read()
    handler_src_start = src.index("async def webssh_session")
    handler_src = src[handler_src_start : src.index("@router.get")]
    assert "ensure_ws_role" in handler_src, "webssh_session must call ensure_ws_role"
    assert "code=4003" in handler_src, "webssh_session must close with code=4003 on denial"


# ── playbook tree source_dir validation (#1046) ────────────────────────────────


def _roots(tmp_path):
    root = tmp_path / "approved"
    root.mkdir(exist_ok=True)
    return [root]


def test_validate_source_dir_accepts_approved_root(tmp_path):
    from fleet_platform.api.routes.ansible.playbooks import validate_source_dir

    roots = _roots(tmp_path)
    result = validate_source_dir(str(roots[0]), roots)
    assert result == roots[0].resolve()


def test_validate_source_dir_rejects_etc(tmp_path):
    import fastapi

    from fleet_platform.api.routes.ansible.playbooks import validate_source_dir

    roots = _roots(tmp_path)
    with pytest.raises(fastapi.HTTPException) as exc_info:
        validate_source_dir("/etc", roots)
    assert exc_info.value.status_code == 403
    assert "not an approved playbook root" in exc_info.value.detail


def test_validate_source_dir_rejects_symlink_escape(tmp_path):
    """A symlink inside an approved root that points outside must be rejected."""
    import os

    from fleet_platform.api.routes.ansible.playbooks import validate_source_dir

    root = tmp_path / "approved"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "escape"
    os.symlink(outside.resolve(), link)
    with pytest.raises(Exception) as exc_info:
        validate_source_dir(str(link), [root])
    assert getattr(exc_info.value, "status_code", None) == 403


def test_validate_source_dir_rejects_parent_traversal(tmp_path):
    """.. traversal out of the approved root must be rejected."""
    from fleet_platform.api.routes.ansible.playbooks import validate_source_dir

    root = tmp_path / "approved"
    sub = root / "sub"
    sub.mkdir(parents=True)
    with pytest.raises(Exception) as exc_info:
        validate_source_dir(str(sub / ".." / ".." / ".."), [root])
    assert getattr(exc_info.value, "status_code", None) == 403


# ── approval email HTML escaping (#1046 item 5) ────────────────────────────────


_CONFIRM_URL = "http://localhost/api/v1/actions/tok"


def test_approval_email_escapes_node_name():
    from fleet_platform.services.pending_action_svc import _build_approval_body

    body = _build_approval_body(
        node_name="<script>alert(1)</script>",
        requested_by="ops@example.com",
        action_type="decommission",
        confirm_url=_CONFIRM_URL,
    )
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body, "node_name must be HTML-escaped"
    assert "<script>" not in body, "raw <script> must never appear in the body"


def test_approval_email_escapes_requested_by_and_action_type():
    from fleet_platform.services.pending_action_svc import _build_approval_body

    body = _build_approval_body(
        node_name="node-1",
        requested_by='bob<x>"y',
        action_type="<b>wipe</b>",
        confirm_url=_CONFIRM_URL,
    )
    assert "bob&lt;x&gt;" in body, "requested_by must be HTML-escaped"
    assert "&lt;b&gt;wipe&lt;/b&gt;" in body, "action_type must be HTML-escaped"
    assert "<x>" not in body
    assert "<b>" not in body
