"""Tests for migration 024: TimescaleDB hypertables conversion.

Verifies that node_health_snapshots and ansible_jobs are properly
converted to TimescaleDB hypertables with correct policies.
"""

from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).parent.parent.parent
    / "fleet_platform/db/migrations/versions/024_timescale_hypertables.py"
)


def load_migration_source() -> str:
    """Load the migration file source code."""
    return MIGRATION_PATH.read_text()


class TestMigrationMetadata:
    """Test basic migration metadata."""

    def test_migration_revision(self) -> None:
        """Test migration revision is 024."""
        migration = load_migration_source()
        assert 'revision = "024"' in migration

    def test_migration_down_revision(self) -> None:
        """Test migration down_revision is 023."""
        migration = load_migration_source()
        assert 'down_revision = "023"' in migration


class TestNodeHealthSnapshotsConversion:
    """Test node_health_snapshots hypertable conversion."""

    def test_hypertable_creation(self) -> None:
        """Test create_hypertable call for node_health_snapshots."""
        migration = load_migration_source()
        assert "create_hypertable('node_health_snapshots'" in migration

    def test_compression_policy(self) -> None:
        """Test add_compression_policy for node_health_snapshots."""
        migration = load_migration_source()
        assert "add_compression_policy('node_health_snapshots'" in migration

    def test_retention_policy(self) -> None:
        """Test add_retention_policy for node_health_snapshots."""
        migration = load_migration_source()
        assert "add_retention_policy('node_health_snapshots'" in migration

    def test_time_column(self) -> None:
        """Test correct time column collected_at is used."""
        migration = load_migration_source()
        # Verify collected_at is used for node_health_snapshots hypertable creation
        assert "'node_health_snapshots', by_range('collected_at'" in migration


class TestAnsibleJobsConversion:
    """Test ansible_jobs hypertable conversion."""

    def test_hypertable_creation(self) -> None:
        """Test create_hypertable call for ansible_jobs."""
        migration = load_migration_source()
        assert "create_hypertable('ansible_jobs'" in migration

    def test_compression_policy(self) -> None:
        """Test add_compression_policy for ansible_jobs."""
        migration = load_migration_source()
        assert "add_compression_policy('ansible_jobs'" in migration

    def test_retention_policy(self) -> None:
        """Test add_retention_policy for ansible_jobs."""
        migration = load_migration_source()
        assert "add_retention_policy('ansible_jobs'" in migration

    def test_time_column(self) -> None:
        """Test correct time column created_at is used."""
        migration = load_migration_source()
        # Verify created_at is used for ansible_jobs hypertable creation
        assert "'ansible_jobs', by_range('created_at'" in migration


class TestDowngradeLogic:
    """Test migration downgrade logic."""

    def test_remove_retention_policies(self) -> None:
        """Test downgrade removes retention policies."""
        migration = load_migration_source()
        assert "remove_retention_policy" in migration
        assert "ansible_jobs" in migration
        assert "node_health_snapshots" in migration

    def test_remove_compression_policies(self) -> None:
        """Test downgrade removes compression policies."""
        migration = load_migration_source()
        assert "remove_compression_policy" in migration
