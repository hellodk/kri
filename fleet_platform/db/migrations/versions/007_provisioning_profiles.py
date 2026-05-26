"""Add provisioning_profiles table."""
import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provisioning_profiles",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("bundle_id", sa.String(255)),
        sa.Column("team_name", sa.String(255)),
        sa.Column("expiry_date", sa.DateTime(timezone=True)),
        sa.Column("profile_type", sa.String(50), nullable=False, server_default="development"),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("provisioning_profiles")
