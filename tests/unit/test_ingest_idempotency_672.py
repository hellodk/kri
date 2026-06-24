"""Tests for pending_actions FK and idempotent process_stats ingest (#672)."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "fleet_platform/db/migrations/versions"


# ---------------------------------------------------------------------------
# Helper: parse module-level constant assignments from a migration file
# ---------------------------------------------------------------------------


def _migration_assignments(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text())
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                out[node.targets[0].id] = "<non-literal>"
    return out


# ---------------------------------------------------------------------------
# Migration 061 — pending_actions FK
# ---------------------------------------------------------------------------


def test_migration_061_exists():
    f = VERSIONS / "061_pending_actions_node_id_fk.py"
    assert f.exists(), "Migration 061_pending_actions_node_id_fk.py not found"


def test_migration_061_revision_chain():
    f = VERSIONS / "061_pending_actions_node_id_fk.py"
    meta = _migration_assignments(f)
    assert meta.get("revision") == "061"
    assert meta.get("down_revision") == "060"


def test_migration_061_creates_fk():
    """Upgrade body must reference create_foreign_key."""
    src = (VERSIONS / "061_pending_actions_node_id_fk.py").read_text()
    assert "create_foreign_key" in src
    assert "pending_actions" in src
    assert "nodes" in src
    assert "SET NULL" in src or "set null" in src.lower()


# ---------------------------------------------------------------------------
# Migration 062 — process_stats unique constraint
# ---------------------------------------------------------------------------


def test_migration_062_exists():
    f = VERSIONS / "062_process_stats_upsert_uniqueness.py"
    assert f.exists(), "Migration 062_process_stats_upsert_uniqueness.py not found"


def test_migration_062_revision_chain():
    f = VERSIONS / "062_process_stats_upsert_uniqueness.py"
    meta = _migration_assignments(f)
    assert meta.get("revision") == "062"
    assert meta.get("down_revision") == "061"


def test_migration_062_creates_unique_constraint():
    src = (VERSIONS / "062_process_stats_upsert_uniqueness.py").read_text()
    assert "create_unique_constraint" in src
    assert "node_process_stats" in src
    assert "node_id" in src
    assert "collected_at" in src
    assert "pid" in src


# ---------------------------------------------------------------------------
# Model: PendingAction.node_id has ForeignKey
# ---------------------------------------------------------------------------


def test_pending_action_node_id_has_fk():
    """pending_actions.node_id must declare a FK to nodes.id."""
    from fleet_platform.models.pending_action import PendingAction

    col = PendingAction.__table__.c["node_id"]
    fks = list(col.foreign_keys)
    assert fks, "pending_actions.node_id has no foreign key"
    targets = {fk.target_fullname for fk in fks}
    assert "nodes.id" in targets, f"Expected FK to nodes.id, got {targets}"


def test_pending_action_node_id_on_delete_set_null():
    """FK on pending_actions.node_id must use ON DELETE SET NULL."""
    from fleet_platform.models.pending_action import PendingAction

    col = PendingAction.__table__.c["node_id"]
    fks = list(col.foreign_keys)
    assert fks
    fk = fks[0]
    assert fk.ondelete is not None and fk.ondelete.upper() == "SET NULL", (
        f"Expected ondelete=SET NULL, got {fk.ondelete!r}"
    )


def test_pending_action_node_id_still_nullable():
    """Adding the FK must not change the nullable semantics — node_id stays nullable."""
    from fleet_platform.models.pending_action import PendingAction

    col = PendingAction.__table__.c["node_id"]
    assert col.nullable, "pending_actions.node_id must remain nullable"


# ---------------------------------------------------------------------------
# Model: NodeProcessStat has the unique constraint
# ---------------------------------------------------------------------------


def test_node_process_stat_unique_constraint_exists():
    """node_process_stats must declare a unique constraint on (node_id, collected_at, pid)."""
    from fleet_platform.models.process_stat import NodeProcessStat

    table = NodeProcessStat.__table__
    unique_constraints = [c for c in table.constraints if hasattr(c, "columns")]
    uq_names = {c.name for c in unique_constraints if c.name}
    assert "uq_node_process_stat_node_ts_pid" in uq_names, (
        f"Expected unique constraint 'uq_node_process_stat_node_ts_pid', got {uq_names}"
    )


def test_node_process_stat_unique_constraint_covers_correct_columns():
    from fleet_platform.models.process_stat import NodeProcessStat

    table = NodeProcessStat.__table__
    for c in table.constraints:
        if getattr(c, "name", None) == "uq_node_process_stat_node_ts_pid":
            col_names = {col.name for col in c.columns}
            assert col_names == {"node_id", "collected_at", "pid"}, f"Unique constraint columns: {col_names}"
            return
    raise AssertionError("Constraint not found")


# ---------------------------------------------------------------------------
# Ingest idempotency: on_conflict_do_nothing in the ingest path
# (read source directly to avoid importing redis dependency in unit tests)
# ---------------------------------------------------------------------------

_INGEST_SRC = (ROOT / "fleet_platform/api/routes/ingest.py").read_text()


def test_ingest_process_stats_uses_on_conflict():
    """ingest_process_stats must use pg_insert with on_conflict_do_nothing."""
    assert "on_conflict_do_nothing" in _INGEST_SRC, (
        "ingest_process_stats must use on_conflict_do_nothing for idempotency"
    )
    assert "pg_insert" in _INGEST_SRC, "ingest_process_stats must import and use pg_insert (PostgreSQL dialect insert)"


def test_ingest_process_stats_conflict_key_includes_pid_and_ts():
    """The conflict key must reference the unique constraint columns."""
    assert "collected_at" in _INGEST_SRC
    assert '"pid"' in _INGEST_SRC or "'pid'" in _INGEST_SRC
    assert '"node_id"' in _INGEST_SRC or "'node_id'" in _INGEST_SRC
