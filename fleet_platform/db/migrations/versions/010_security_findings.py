"""security_findings

Revision ID: 010
Revises: 009
Create Date: 2026-05-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vulnerability_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("scanner", sa.String(30), nullable=False),
        sa.Column("cve_id", sa.String(30), nullable=False),
        sa.Column("package_name", sa.String(255), nullable=False),
        sa.Column("package_version", sa.String(100), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("cvss_score", sa.Float(), nullable=True),
        sa.Column("fixed_version", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference_url", sa.String(500), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_vuln_findings_node_severity", "vulnerability_findings", ["node_id", "severity"])
    op.create_index("idx_vuln_findings_cve", "vulnerability_findings", ["cve_id"])

    op.create_table(
        "license_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("scanner", sa.String(30), nullable=False),
        sa.Column("package_name", sa.String(255), nullable=False),
        sa.Column("package_version", sa.String(100), nullable=True),
        sa.Column("license_id", sa.String(100), nullable=False),
        sa.Column("risk", sa.String(20), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_license_findings_node", "license_findings", ["node_id"])
    op.create_index("idx_license_findings_risk", "license_findings", ["node_id", "risk"])


def downgrade():
    op.drop_table("license_findings")
    op.drop_table("vulnerability_findings")
