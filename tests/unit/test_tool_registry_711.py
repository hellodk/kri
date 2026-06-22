"""#711 Phase B — tool registry: validation, RBAC filtering, kill-switch, exports."""

import pytest

from fleet_platform.agent.registry import SIDE_EFFECTS, ToolCtx, ToolRegistry, ToolSpec

OBJ_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"node_id": {"type": "string", "description": "target node"}},
    "required": ["node_id"],
}


def _spec(name="get_node", role="viewer", side_effect="read", enabled=True):
    return ToolSpec(
        name=name,
        description="desc",
        params_schema=OBJ_SCHEMA,
        required_role=role,
        side_effect=side_effect,
        enabled=enabled,
    )


# --- ToolSpec validation -----------------------------------------------------


def test_valid_spec_constructs():
    s = _spec()
    assert s.name == "get_node"
    assert s.enabled is True


@pytest.mark.parametrize("bad", ["", "bad name", "weird!", "a-b"])
def test_invalid_name_rejected(bad):
    with pytest.raises(ValueError):
        _spec(name=bad)


def test_invalid_side_effect_rejected():
    with pytest.raises(ValueError):
        ToolSpec(name="t", description="d", params_schema=OBJ_SCHEMA, side_effect="nuke")


def test_invalid_role_rejected():
    with pytest.raises(ValueError):
        ToolSpec(name="t", description="d", params_schema=OBJ_SCHEMA, required_role="root")


def test_non_object_schema_rejected():
    with pytest.raises(ValueError):
        ToolSpec(name="t", description="d", params_schema={"type": "string"})


def test_spec_is_frozen():
    s = _spec()
    with pytest.raises(Exception):
        s.name = "other"  # type: ignore[misc]


def test_all_side_effects_accepted():
    for se in SIDE_EFFECTS:
        ToolSpec(name="t", description="d", params_schema=OBJ_SCHEMA, side_effect=se, required_role="admin")


# --- schema exporters --------------------------------------------------------


def test_to_openai_tool_shape():
    t = _spec().to_openai_tool()
    assert t["type"] == "function"
    assert t["function"]["name"] == "get_node"
    assert t["function"]["parameters"] == OBJ_SCHEMA


def test_to_anthropic_tool_shape():
    t = _spec().to_anthropic_tool()
    assert t["name"] == "get_node"
    assert t["input_schema"] == OBJ_SCHEMA


def test_to_prompt_section_lists_args():
    text = _spec().to_prompt_section()
    assert "get_node" in text
    assert "node_id" in text
    assert "required" in text


# --- registry: register / get -----------------------------------------------


def test_register_and_get():
    r = ToolRegistry()
    r.register(_spec())
    assert r.get("get_node").name == "get_node"
    assert r.get("missing") is None
    assert len(r.all()) == 1


def test_duplicate_registration_rejected():
    r = ToolRegistry()
    r.register(_spec())
    with pytest.raises(ValueError):
        r.register(_spec())


# --- RBAC filtering + kill-switch -------------------------------------------


def _registry_with_tiers():
    r = ToolRegistry()
    r.register(_spec(name="read_v", role="viewer", side_effect="read"))
    r.register(_spec(name="exec_o", role="operator", side_effect="execute_read"))
    r.register(_spec(name="write_a", role="admin", side_effect="write_live"))
    r.register(_spec(name="killed", role="viewer", side_effect="read", enabled=False))
    return r


def test_viewer_sees_only_viewer_tools():
    r = _registry_with_tiers()
    names = {t.name for t in r.available_for_role("viewer")}
    assert names == {"read_v"}


def test_operator_sees_viewer_and_operator():
    r = _registry_with_tiers()
    names = {t.name for t in r.available_for_role("operator")}
    assert names == {"read_v", "exec_o"}


def test_admin_sees_all_enabled():
    r = _registry_with_tiers()
    names = {t.name for t in r.available_for_role("admin")}
    assert names == {"read_v", "exec_o", "write_a"}


def test_killswitched_tool_is_never_exposed():
    r = _registry_with_tiers()
    for role in ("viewer", "operator", "admin"):
        assert "killed" not in {t.name for t in r.available_for_role(role)}


def test_unknown_role_sees_nothing():
    r = _registry_with_tiers()
    assert r.available_for_role(None) == []
    assert r.available_for_role("root") == []


def test_export_helpers_respect_role():
    r = _registry_with_tiers()
    assert len(r.to_openai_tools("viewer")) == 1
    assert len(r.to_anthropic_tools("operator")) == 2
    assert len(r.to_openai_tools("admin")) == 3
    section = r.to_prompt_section("viewer")
    assert "read_v" in section and "write_a" not in section


def test_prompt_section_empty_when_no_tools():
    r = ToolRegistry()
    assert "No tools" in r.to_prompt_section("admin")


# --- ToolCtx -----------------------------------------------------------------


def test_tool_ctx_defaults():
    ctx = ToolCtx(actor="alice@org", role="operator")
    assert ctx.actor == "alice@org"
    assert ctx.session_id is None
    assert ctx.extra == {}
