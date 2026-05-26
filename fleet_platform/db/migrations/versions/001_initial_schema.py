"""Initial schema — all tables + TimescaleDB hypertables

Revision ID: 001
Revises:
Create Date: 2026-05-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_users_email", "users", ["email"])

    # nodes
    op.create_table(
        "nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("minion_id", sa.String(255), unique=True, nullable=False),
        sa.Column("hostname", sa.String(255), nullable=True),
        sa.Column("ip_address", postgresql.INET, nullable=True),
        sa.Column("os_version", sa.String(50), nullable=True),
        sa.Column("os_build", sa.String(50), nullable=True),
        sa.Column("hardware_model", sa.String(100), nullable=True),
        sa.Column("cpu_cores", sa.SmallInteger, nullable=True),
        sa.Column("ram_gb", sa.Numeric(8, 2), nullable=True),
        sa.Column("storage_gb", sa.Numeric(10, 2), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("drift_score", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("node_token_hash", sa.String(72), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_nodes_status", "nodes", ["status"])
    op.create_index("idx_nodes_drift_score", "nodes", ["drift_score"])
    op.create_index("idx_nodes_last_seen", "nodes", ["last_seen_at"])

    # tags
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("node_id", "key", name="uq_tags_node_key"),
    )
    op.create_index("idx_tags_node_id", "tags", ["node_id"])
    op.create_index("idx_tags_key_value", "tags", ["key", "value"])

    # groups
    op.create_table(
        "groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("predicate", postgresql.JSONB, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # group_members
    op.create_table(
        "group_members",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_group_members_node_id", "group_members", ["node_id"])

    # node_facts — TimescaleDB hypertable
    op.create_table(
        "node_facts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("grains", postgresql.JSONB, nullable=False),
    )
    op.create_index("idx_node_facts_node_id", "node_facts", ["node_id", "collected_at"])
    op.execute(
        "SELECT create_hypertable('node_facts', by_range('collected_at', INTERVAL '1 day'))"
    )
    op.execute("SELECT add_retention_policy('node_facts', INTERVAL '90 days')")

    # desired_state_baselines
    op.create_table(
        "desired_state_baselines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("git_commit_sha", sa.String(40), nullable=False),
        sa.Column("state_json", postgresql.JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # drift_records — TimescaleDB hypertable
    op.create_table(
        "drift_records",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("baseline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("desired_state_baselines.id", ondelete="SET NULL"), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("drift_score", sa.SmallInteger, nullable=False),
        sa.Column("missing_packages", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("extra_packages", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("version_mismatches", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("service_drift", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("config_drift", postgresql.JSONB, nullable=False, server_default="[]"),
    )
    op.create_index("idx_drift_records_node_id", "drift_records", ["node_id", "computed_at"])
    op.create_index("idx_drift_records_score", "drift_records", ["drift_score", "computed_at"])
    op.execute(
        "SELECT create_hypertable('drift_records', by_range('computed_at', INTERVAL '1 day'))"
    )
    op.execute("SELECT add_retention_policy('drift_records', INTERVAL '180 days')")

    # sbom_scans
    op.create_table(
        "sbom_scans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("syft_version", sa.String(20), nullable=True),
        sa.Column("format", sa.String(20), nullable=False, server_default="cyclonedx"),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("component_count", sa.Integer, nullable=True),
    )
    op.create_index("idx_sbom_scans_node_id", "sbom_scans", ["node_id", "scanned_at"])

    # sbom_components
    op.create_table(
        "sbom_components",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("scan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sbom_scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(100), nullable=True),
        sa.Column("purl", sa.String(500), nullable=True),
        sa.Column("component_type", sa.String(50), nullable=True),
        sa.Column("licenses", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("cpes", postgresql.JSONB, nullable=False, server_default="[]"),
    )
    op.execute("""
        ALTER TABLE sbom_components
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english',
                name || ' ' ||
                COALESCE(version, '') || ' ' ||
                COALESCE(purl, '')
            )
        ) STORED
    """)
    op.create_index("idx_sbom_components_search", "sbom_components", ["search_vector"], postgresql_using="gin")
    op.create_index("idx_sbom_components_node_id", "sbom_components", ["node_id"])
    op.create_index("idx_sbom_components_name", "sbom_components", ["name"])
    op.create_index("idx_sbom_components_purl", "sbom_components", ["purl"])

    # execution_jobs
    op.create_table(
        "execution_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("salt_jid", sa.String(100), nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("triggered_by", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_exec_jobs_status", "execution_jobs", ["status", "started_at"])
    op.create_index("idx_exec_jobs_salt_jid", "execution_jobs", ["salt_jid"])

    # execution_results
    op.create_table(
        "execution_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("execution_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("stdout", sa.Text, nullable=True),
        sa.Column("stderr", sa.Text, nullable=True),
        sa.Column("changes", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_exec_results_job_id", "execution_results", ["job_id"])
    op.create_index("idx_exec_results_node_id", "execution_results", ["node_id", "completed_at"])

    # audit_events — TimescaleDB hypertable
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("old_value", postgresql.JSONB, nullable=True),
        sa.Column("new_value", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", postgresql.INET, nullable=True),
    )
    op.create_index("idx_audit_events_actor", "audit_events", ["actor", "event_at"])
    op.create_index("idx_audit_events_resource", "audit_events", ["resource_type", "resource_id", "event_at"])
    op.execute(
        "SELECT create_hypertable('audit_events', by_range('event_at', INTERVAL '7 days'))"
    )
    op.execute("SELECT add_retention_policy('audit_events', INTERVAL '730 days')")

    # Continuous aggregate for fleet drift dashboard
    op.execute("""
        CREATE MATERIALIZED VIEW fleet_drift_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', computed_at) AS bucket,
            AVG(drift_score)::SMALLINT AS avg_drift_score,
            MAX(drift_score) AS max_drift_score,
            COUNT(*) FILTER (WHERE drift_score > 50) AS nodes_high_drift,
            COUNT(DISTINCT node_id) AS nodes_evaluated
        FROM drift_records
        GROUP BY bucket
        WITH NO DATA
    """)
    op.execute("""
        SELECT add_continuous_aggregate_policy('fleet_drift_hourly',
            start_offset => INTERVAL '3 hours',
            end_offset   => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour')
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS fleet_drift_hourly")
    op.drop_table("audit_events")
    op.drop_table("execution_results")
    op.drop_table("execution_jobs")
    op.drop_table("sbom_components")
    op.drop_table("sbom_scans")
    op.drop_table("drift_records")
    op.drop_table("desired_state_baselines")
    op.drop_table("node_facts")
    op.drop_table("group_members")
    op.drop_table("groups")
    op.drop_table("tags")
    op.drop_table("nodes")
    op.drop_table("users")
