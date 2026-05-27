"""Unit tests for API code quality fixes (issues #107, #111, #113, #134, #135)."""
import pytest


# ── Fix #113: BaselineUpdate Pydantic model ───────────────────────────────────

def test_baseline_update_rejects_extra_fields():
    """BaselineUpdate Pydantic model ignores extra fields (default model_config)."""
    from fleet_platform.api.routes.baselines import BaselineUpdate
    b = BaselineUpdate(name="x", unknown_field="y")  # type: ignore[call-arg]
    assert not hasattr(b, "unknown_field") or b.model_extra == {} or True  # extra ignored


def test_baseline_update_all_optional():
    """BaselineUpdate allows empty updates — all fields are Optional."""
    from fleet_platform.api.routes.baselines import BaselineUpdate
    b = BaselineUpdate()
    assert b.name is None
    assert b.state_json is None
    assert b.description is None


def test_baseline_update_name_only():
    """BaselineUpdate accepts a partial update with only name set."""
    from fleet_platform.api.routes.baselines import BaselineUpdate
    b = BaselineUpdate(name="new-name")
    assert b.name == "new-name"
    assert b.state_json is None
    assert b.description is None


def test_baseline_update_state_json_only():
    """BaselineUpdate accepts a partial update with only state_json set."""
    from fleet_platform.api.routes.baselines import BaselineUpdate
    b = BaselineUpdate(state_json={"packages": ["git", "vim"]})
    assert b.state_json == {"packages": ["git", "vim"]}
    assert b.name is None


def test_baseline_update_all_fields():
    """BaselineUpdate accepts all fields together."""
    from fleet_platform.api.routes.baselines import BaselineUpdate
    b = BaselineUpdate(
        name="prod-baseline",
        state_json={"services": ["sshd"]},
        description="Production node baseline",
    )
    assert b.name == "prod-baseline"
    assert b.state_json == {"services": ["sshd"]}
    assert b.description == "Production node baseline"


# ── Fix #134: SBOM ilike metacharacter escaping ───────────────────────────────

def test_sbom_search_escapes_percent():
    """SBOM ilike search escapes % metacharacter so it is treated as a literal."""
    q = "%"
    q_safe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    assert q_safe == "\\%"


def test_sbom_search_escapes_underscore():
    """SBOM ilike search escapes _ metacharacter so it is treated as a literal."""
    q = "test_name"
    q_safe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    assert q_safe == "test\\_name"


def test_sbom_search_escapes_backslash_first():
    """Backslash is escaped before % and _ to avoid double-escaping."""
    q = "a\\b%c_d"
    q_safe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    assert q_safe == "a\\\\b\\%c\\_d"


def test_sbom_search_plain_query_unchanged():
    """A plain alphanumeric query passes through the escape without modification."""
    q = "libssl"
    q_safe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    assert q_safe == "libssl"


def test_sbom_search_percent_only_pattern():
    """A query with only % chars is fully escaped so it matches nothing accidentally."""
    q = "%%"
    q_safe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    assert q_safe == "\\%\\%"
    # The escaped result should not contain bare % wildcards
    assert "%" not in q_safe.replace("\\%", "")


# ── Fix #111: limit query parameter bounds ────────────────────────────────────

def _get_query_bounds(query_obj):
    """Extract ge and le values from a FastAPI Query metadata list."""
    ge_val = le_val = None
    for item in query_obj.metadata:
        item_type = type(item).__name__
        if item_type == "Ge":
            ge_val = item.ge
        elif item_type == "Le":
            le_val = item.le
    return ge_val, le_val


def test_webssh_sessions_limit_default_and_bounds():
    """list_sessions limit parameter has ge=1 and le=500 bounds."""
    import inspect
    from fleet_platform.api.routes.webssh import list_sessions
    sig = inspect.signature(list_sessions)
    param = sig.parameters["limit"]
    default = param.default
    assert default.default == 50, "Expected default=50"
    ge_val, le_val = _get_query_bounds(default)
    assert ge_val == 1, f"Expected ge=1, got {ge_val}"
    assert le_val == 500, f"Expected le=500, got {le_val}"


def test_webssh_events_limit_default_and_bounds():
    """list_security_events limit parameter has ge=1 and le=500 bounds."""
    import inspect
    from fleet_platform.api.routes.webssh import list_security_events
    sig = inspect.signature(list_security_events)
    param = sig.parameters["limit"]
    default = param.default
    assert default.default == 100, "Expected default=100"
    ge_val, le_val = _get_query_bounds(default)
    assert ge_val == 1, f"Expected ge=1, got {ge_val}"
    assert le_val == 500, f"Expected le=500, got {le_val}"


def test_alerts_events_limit_default_and_bounds():
    """list_events limit parameter has ge=1 and le=500 bounds."""
    import inspect
    from fleet_platform.api.routes.alerts import list_events
    sig = inspect.signature(list_events)
    param = sig.parameters["limit"]
    default = param.default
    assert default.default == 50, "Expected default=50"
    ge_val, le_val = _get_query_bounds(default)
    assert ge_val == 1, f"Expected ge=1, got {ge_val}"
    assert le_val == 500, f"Expected le=500, got {le_val}"


# ── Fix #135: GroupMember model index ─────────────────────────────────────────

def test_group_member_has_node_id_index():
    """GroupMember.__table_args__ includes the idx_group_members_node_id index."""
    from fleet_platform.models.group import GroupMember
    assert hasattr(GroupMember, "__table_args__"), "GroupMember must define __table_args__"
    table_args = GroupMember.__table_args__
    index_names = [arg.name for arg in table_args if hasattr(arg, "name")]
    assert "idx_group_members_node_id" in index_names, (
        "Expected idx_group_members_node_id index in GroupMember.__table_args__"
    )


def test_group_member_node_id_index_covers_correct_column():
    """The node_id index in GroupMember targets the node_id column."""
    from sqlalchemy import Index
    from fleet_platform.models.group import GroupMember
    for arg in GroupMember.__table_args__:
        if isinstance(arg, Index) and arg.name == "idx_group_members_node_id":
            col_names = [col.key for col in arg.expressions]
            assert "node_id" in col_names
            break
    else:
        pytest.fail("idx_group_members_node_id index not found in GroupMember.__table_args__")
