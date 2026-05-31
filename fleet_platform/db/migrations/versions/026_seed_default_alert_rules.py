"""Seed default alert rules.

Audit finding C-2 (Principal SRE): node_offline alerting is completely opt-in;
no default rule exists so most fleets never receive offline alerts.

This migration inserts the default node_offline rule if it is not already present,
making monitoring work out-of-the-box without manual UI configuration.
"""
import sqlalchemy as sa
from alembic import op

revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Insert default node_offline rule only if no node_offline rule exists yet.
    # Using INSERT ... WHERE NOT EXISTS so re-running is safe (idempotent).
    conn.execute(sa.text("""
        INSERT INTO alert_rules (name, event_type, threshold, enabled)
        SELECT
            'Node Offline (default)',
            'node_offline',
            NULL,
            TRUE
        WHERE NOT EXISTS (
            SELECT 1 FROM alert_rules WHERE event_type = 'node_offline'
        )
    """))


def downgrade() -> None:
    # Only remove the rule we created (by exact name); leave operator-created rules alone.
    op.execute(
        "DELETE FROM alert_rules WHERE name = 'Node Offline (default)' AND event_type = 'node_offline'"
    )
