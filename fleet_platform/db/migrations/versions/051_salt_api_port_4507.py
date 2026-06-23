"""Change salt_api_port server_default from 8080 to 4507.

Revision ID: 051
Revises: 050
Create Date: 2026-06-21

New masters provisioned via the API will default to port 4507 (adjacent to
salt's ZMQ ports 4505/4506, avoids conflict with 8080 web traffic).
Existing DB rows are NOT rewritten — they keep their stored port value.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "salt_masters",
        "salt_api_port",
        server_default="4507",
    )


def downgrade() -> None:
    op.alter_column(
        "salt_masters",
        "salt_api_port",
        server_default="8080",
    )
