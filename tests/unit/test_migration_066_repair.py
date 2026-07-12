"""Migration 066 repairs the credential_id columns an early 065 variant dropped."""

from pathlib import Path

_M = (
    Path(__file__).resolve().parents[2]
    / "fleet_platform" / "db" / "migrations" / "versions" / "066_repair_credential_id_columns.py"
).read_text()


def test_066_revises_065():
    assert 'revision = "066"' in _M
    assert 'down_revision = "065"' in _M


def test_066_readds_both_columns_idempotently():
    assert 'add_column("nodes", sa.Column("credential_id"' in _M
    assert 'add_column("groups", sa.Column("credential_id"' in _M
    # Guarded so it is a no-op where the columns still exist.
    assert "_has_column" in _M
    # Repair migration must NOT drop them again.
    assert "drop_column" not in _M
