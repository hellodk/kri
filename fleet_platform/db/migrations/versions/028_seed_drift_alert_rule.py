"""Seed default drift_threshold alert rule.

Any node exceeding drift score 50 will fire an alert (and email if SMTP configured).
Threshold matches _DEFAULT_OFFLINE_HOURS spirit: 50 = "High" severity in drift engine.
"""
from alembic import op
import sqlalchemy as sa

revision = '028'
down_revision = '027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO alert_rules (name, event_type, threshold, enabled)
        SELECT
            'High Drift Score (default)',
            'drift_threshold',
            50,
            TRUE
        WHERE NOT EXISTS (
            SELECT 1 FROM alert_rules WHERE event_type = 'drift_threshold'
        )
    """))


def downgrade() -> None:
    op.execute(
        "DELETE FROM alert_rules WHERE name = 'High Drift Score (default)' AND event_type = 'drift_threshold'"
    )
