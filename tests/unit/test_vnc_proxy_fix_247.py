"""Tests for VNC proxy fix (#247) — raw bridge, no server-side auth."""


def test_vnc_rfb_auth_function_still_exists():
    """_rfb_auth must still exist (has unit tests, kept for reference)."""
    from fleet_platform.api.routes.vnc import _rfb_auth, _vnc_des_key

    assert callable(_rfb_auth)
    assert callable(_vnc_des_key)


def test_vnc_session_does_not_call_rfb_auth():
    """The vnc_session WebSocket handler must NOT call _rfb_auth (causes double-handshake #247).

    We verify by checking that _rfb_auth does not appear in the function's bytecode name
    references (co_names), which is the canonical set of global/attribute names the function
    ever accesses at runtime. This is a code-object inspection, not source text scraping.
    """

    from fleet_platform.api.routes.vnc import vnc_session

    # co_names contains every LOAD_GLOBAL / LOAD_ATTR name the function references.
    # If _rfb_auth is called, its name will appear here.
    all_names: set[str] = set(vnc_session.__code__.co_names)
    # Also walk nested code objects (inner async functions / comprehensions)
    import types

    def _collect_names(code: types.CodeType) -> set[str]:
        names = set(code.co_names)
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                names |= _collect_names(const)
        return names

    all_names = _collect_names(vnc_session.__code__)

    assert "_rfb_auth" not in all_names, (
        "vnc_session must NOT reference _rfb_auth — noVNC handles the RFB protocol. "
        "See #247: proxy auth conflicts with noVNC's own handshake."
    )


def test_vnc_creds_route_exists():
    """GET /session/{node_id}/creds route must exist."""
    from fleet_platform.api.routes.vnc import router

    paths = [r.path for r in router.routes]
    assert any("creds" in p for p in paths), f"creds route not in {paths}"


def test_node_update_schema_accepts_vnc_password():
    """NodeUpdateRequest schema must include a vnc_password field (confirms #256 storage is wired)."""
    from fleet_platform.schemas.fleet import NodeUpdateRequest

    assert "vnc_password" in NodeUpdateRequest.model_fields, "NodeUpdateRequest must have a vnc_password field (#256)"
