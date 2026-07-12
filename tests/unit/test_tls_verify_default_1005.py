"""Tests for #1005 S3: salt_masters.tls_verify must default to True.

Previously tls_verify defaulted to False, so salt-api calls skipped TLS
verification unless an operator opted in — MITM-able on a hostile LAN.
Covers both the ORM-level default (fleet_platform/models/salt_master.py)
and the new alembic migration that flips the column's server_default.
"""

from pathlib import Path

from fleet_platform.models.salt_master import SaltMaster

MIGRATION_PATH = (
    Path(__file__).parent.parent.parent
    / "fleet_platform/db/migrations/versions/068_salt_master_tls_verify_default_true.py"
)


def load_migration_source() -> str:
    return MIGRATION_PATH.read_text()


class TestSaltMasterModelDefault:
    def test_tls_verify_column_default_is_true(self) -> None:
        column = SaltMaster.__table__.columns["tls_verify"]
        assert column.default is not None
        assert column.default.arg is True

    def test_tls_verify_still_not_nullable(self) -> None:
        column = SaltMaster.__table__.columns["tls_verify"]
        assert column.nullable is False


class TestMigration068Metadata:
    def test_migration_file_exists(self) -> None:
        assert MIGRATION_PATH.exists()

    def test_migration_revision(self) -> None:
        migration = load_migration_source()
        assert 'revision = "068"' in migration

    def test_migration_down_revision(self) -> None:
        migration = load_migration_source()
        assert 'down_revision = "067"' in migration

    def test_upgrade_sets_server_default_true(self) -> None:
        migration = load_migration_source()
        upgrade_body = migration.split("def upgrade()")[1].split("def downgrade()")[0]
        assert "tls_verify" in upgrade_body
        assert 'server_default=sa.text("true")' in upgrade_body

    def test_downgrade_restores_server_default_false(self) -> None:
        migration = load_migration_source()
        downgrade_body = migration.split("def downgrade()")[1]
        assert "tls_verify" in downgrade_body
        assert 'server_default=sa.text("false")' in downgrade_body

    def test_migration_documents_existing_rows_unchanged(self) -> None:
        """Docstring must call out that existing rows are not backfilled."""
        migration = load_migration_source()
        assert "does" in migration.lower() and "not" in migration.lower()
        assert "backfill" in migration.lower() or "existing rows" in migration.lower()
