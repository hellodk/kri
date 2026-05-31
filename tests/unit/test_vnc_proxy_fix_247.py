"""Tests for VNC proxy fix (#247) — raw bridge, no server-side auth."""
import ast
import inspect


def test_vnc_rfb_auth_function_still_exists():
    """_rfb_auth must still exist (has unit tests, kept for reference)."""
    from fleet_platform.api.routes.vnc import _rfb_auth, _vnc_des_key
    assert callable(_rfb_auth)
    assert callable(_vnc_des_key)


def test_vnc_session_does_not_call_rfb_auth():
    """The vnc_session WebSocket handler must NOT call _rfb_auth (causes double-handshake #247)."""
    import fleet_platform.api.routes.vnc as vnc_mod

    source = inspect.getsource(vnc_mod.vnc_session)
    # Parse the source to check for _rfb_auth calls
    tree = ast.parse(source)
    calls = [
        node.func.id if isinstance(node.func, ast.Name) else
        node.func.attr if isinstance(node.func, ast.Attribute) else ''
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    ]
    assert "_rfb_auth" not in calls, (
        "vnc_session must NOT call _rfb_auth — noVNC handles the RFB protocol. "
        "See #247: proxy auth conflicts with noVNC's own handshake."
    )


def test_vnc_creds_route_exists():
    """GET /session/{node_id}/creds route must exist."""
    from fleet_platform.api.routes.vnc import router
    paths = [r.path for r in router.routes]
    assert any("creds" in p for p in paths), f"creds route not in {paths}"


def test_node_update_schema_accepts_vnc_password():
    """nodes route must handle vnc_password (confirms #256 storage is wired)."""
    import fleet_platform.api.routes.nodes as nodes_mod
    source = inspect.getsource(nodes_mod)
    assert "vnc_password" in source, "nodes route must handle vnc_password (#256)"
