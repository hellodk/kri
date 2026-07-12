"""Issue #983 Phase 1 (expand-contract) — credential_groups association table.

This is the *expand* phase: the new `credential_groups` association model +
migration are ADDED, backfilled from `Group.credential_id`, but the embedded
`Group.credential_id` / `Node.credential_id` columns are KEPT and the resolver is
unchanged — so every existing caller keeps working and the branch is deploy-safe.
The resolver cutover, caller migration, and (final phase) column drop come later.

See docs/superpowers/specs/2026-07-12-credentials-groups-nodes-model-design.md.
"""

from pathlib import Path

from fleet_platform.models.credential_group import CredentialGroup
from fleet_platform.models.group import Group
from fleet_platform.models.node import Node

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "fleet_platform"
    / "db"
    / "migrations"
    / "versions"
    / "065_credential_groups_normalized.py"
)


# ── new association model ────────────────────────────────────────────────────


def test_credential_group_model_exists_with_fks():
    cols = CredentialGroup.__table__.columns
    assert "credential_id" in cols
    assert "group_id" in cols
    assert CredentialGroup.__tablename__ == "credential_groups"


def test_credential_group_has_unique_group_id():
    # One credential per group — enforced by a UNIQUE(group_id) constraint.
    uniques = [c for c in CredentialGroup.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
    cols = {tuple(col.name for col in u.columns) for u in uniques}
    assert ("group_id",) in cols


# ── expand-contract: old columns are KEPT this phase ─────────────────────────


def test_group_and_node_still_have_credential_id_this_phase():
    assert "credential_id" in Group.__table__.columns
    assert "credential_id" in Node.__table__.columns


# ── migration is additive (no drops in the expand phase) ─────────────────────


def test_migration_is_additive_no_column_drops():
    src = _MIGRATION.read_text()
    assert 'down_revision = "064"' in src
    assert 'revision = "065"' in src
    assert "credential_groups" in src
    assert 'drop_column("groups", "credential_id")' not in src
    assert 'drop_column("nodes", "credential_id")' not in src


def test_migration_backfills_and_seeds_default():
    src = _MIGRATION.read_text()
    assert "default-bootstrap" in src  # default credential seeded
    assert "uq_credential_groups_group_id" in src
