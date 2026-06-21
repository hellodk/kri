"""#710 Phase A — agent data model + migration 052 guards.

DB-free: validates the migration chain stays linear and the ORM models expose
the new agentic columns. Behavioural DB tests live in the integration suite.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "fleet_platform/db/migrations/versions"


def _module_assignments(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text())
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                out[node.targets[0].id] = "<non-literal>"
    return out


def _all_migration_files() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if p.name != "__init__.py")


def test_migration_052_chains_from_051():
    migration = VERSIONS / "052_agent_sessions_foundations.py"
    assert migration.exists(), "Migration 052 file not found"
    a = _module_assignments(migration)
    assert a["revision"] == "052"
    assert a["down_revision"] == "051"


def test_full_migration_chain_remains_linear():
    revs: dict[str, str | None] = {}
    for p in _all_migration_files():
        a = _module_assignments(p)
        revs[str(a.get("revision"))] = a.get("down_revision")  # type: ignore[assignment]

    roots = [r for r, d in revs.items() if d is None]
    assert len(roots) == 1, f"expected one root migration, got {roots}"

    known = set(revs)
    dangling = [(r, d) for r, d in revs.items() if d is not None and d not in known]
    assert not dangling, f"down_revision points to unknown revision(s): {dangling}"

    parents = [d for d in revs.values() if d is not None]
    dupes = {d for d in parents if parents.count(d) > 1}
    assert not dupes, f"multiple heads / branch detected: {dupes}"


# ---------------------------------------------------------------------------
# ORM model introspection
# ---------------------------------------------------------------------------


def test_agent_session_is_registered_in_models_package():
    from fleet_platform.models import AgentSession

    assert AgentSession.__tablename__ == "agent_sessions"


def test_agent_session_columns():
    from fleet_platform.models.agent_session import AgentSession

    cols = {c.name for c in AgentSession.__table__.columns}
    assert {
        "id",
        "user_id",
        "endpoint_id",
        "status",
        "initial_prompt",
        "iteration_count",
        "tool_call_count",
        "error",
        "created_at",
        "updated_at",
    } <= cols


def test_agent_session_status_validation():
    from fleet_platform.models.agent_session import AgentSession

    assert AgentSession.is_valid_status("active")
    assert AgentSession.is_valid_status("completed")
    assert not AgentSession.is_valid_status("running")
    assert not AgentSession.is_valid_status("")


def test_llm_query_log_has_agentic_columns():
    from fleet_platform.models.llm_query_log import LLMQueryLog

    cols = {c.name for c in LLMQueryLog.__table__.columns}
    assert {"tool_calls", "parent_query_id", "agent_session_id"} <= cols


def test_pending_action_has_agent_write_path_columns():
    from fleet_platform.models.pending_action import PendingAction

    cols = {c.name for c in PendingAction.__table__.columns}
    assert {
        "session_id",
        "proposed_by_agent",
        "tool_name",
        "target_count",
        "dry_run_result",
        "co_sign_required",
    } <= cols


def test_pending_action_agent_defaults_are_safe():
    """proposed_by_agent / co_sign_required must default false at the DB layer."""
    from fleet_platform.models.pending_action import PendingAction

    for name in ("proposed_by_agent", "co_sign_required"):
        col = PendingAction.__table__.columns[name]
        assert col.server_default is not None
        assert "false" in str(col.server_default.arg).lower()
