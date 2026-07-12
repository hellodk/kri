"""Normalized credential model — credential_groups association table (#983).

Revision ID: 065
Revises: 064
Create Date: 2026-07-12

Phase 1 of the normalized credential model (docs/superpowers/specs/
2026-07-12-credentials-groups-nodes-model-design.md). Replaces the embedded
``Group.credential_id`` / ``Node.credential_id`` FKs with a single association
table: one credential per group (``UNIQUE(group_id)``), a credential may cover
many groups.

Steps:
1. Create ``credential_groups(id, credential_id, group_id, created_at)``.
2. Backfill: every ``Group.credential_id`` becomes a ``credential_groups`` row.
3. Create a "default" group + a "default-bootstrap" Credential seeded from the
   global bootstrap SSH settings, mapped to the default group (idempotent).
4. Any node not already resolvable via a credential-bearing group is added to
   the default group.
5. Drop ``groups.credential_id`` and ``nodes.credential_id`` (and their FK/index).

This migration is NOT executed/verified against a live database as part of
#983 Phase 1 — schema/resolver only. Verify against a real (or disposable
staging) Postgres instance before merging/deploying.
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


# --- lightweight table handles for core (non-ORM) statements -----------------


def _groups_t():
    return sa.table(
        "groups",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("credential_id", postgresql.UUID(as_uuid=True)),
    )


def _credentials_t():
    return sa.table(
        "credentials",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("kind", sa.String),
        sa.column("username", sa.String),
        sa.column("secret_enc", sa.Text),
    )


def _credential_groups_t():
    return sa.table(
        "credential_groups",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("credential_id", postgresql.UUID(as_uuid=True)),
        sa.column("group_id", postgresql.UUID(as_uuid=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )


def _nodes_t():
    return sa.table(
        "nodes",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("credential_id", postgresql.UUID(as_uuid=True)),
    )


def _group_members_t():
    return sa.table(
        "group_members",
        sa.column("group_id", postgresql.UUID(as_uuid=True)),
        sa.column("node_id", postgresql.UUID(as_uuid=True)),
        sa.column("added_at", sa.DateTime(timezone=True)),
    )


def _platform_settings_t():
    return sa.table(
        "platform_settings",
        sa.column("key", sa.String),
        sa.column("value", sa.Text),
    )


def upgrade() -> None:
    bind = op.get_bind()
    now = sa.func.now()

    # 1. credential_groups association table.
    op.create_table(
        "credential_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "credential_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("credentials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", name="uq_credential_groups_group_id"),
    )
    op.create_index("idx_credential_groups_credential_id", "credential_groups", ["credential_id"])

    groups_t = _groups_t()
    credentials_t = _credentials_t()
    credential_groups_t = _credential_groups_t()
    platform_settings_t = _platform_settings_t()

    # 2. Backfill: every Group.credential_id -> a credential_groups row.
    existing_groups = bind.execute(
        sa.select(groups_t.c.id, groups_t.c.credential_id).where(groups_t.c.credential_id.isnot(None))
    ).fetchall()
    for row in existing_groups:
        bind.execute(
            credential_groups_t.insert().values(
                id=uuid.uuid4(),
                credential_id=row.credential_id,
                group_id=row.id,
                created_at=now,
            )
        )

    # 3. Default group + default-bootstrap Credential (idempotent).
    default_group = bind.execute(sa.select(groups_t.c.id).where(groups_t.c.name == "default")).fetchone()
    if default_group is not None:
        default_group_id = default_group.id
    else:
        default_group_id = uuid.uuid4()
        # `groups` has several NOT NULL columns without server defaults
        # (created_at/updated_at via TimestampMixin, type). Use a raw INSERT
        # with explicit values for those columns.
        bind.execute(
            sa.text(
                """
                INSERT INTO groups (id, name, type, session_max_mins, session_retention_days,
                                     credential_priority, created_at, updated_at)
                VALUES (:id, :name, :type, 60, 30, 0, now(), now())
                """
            ),
            {"id": default_group_id, "name": "default", "type": "static"},
        )

    default_cred = bind.execute(
        sa.select(credentials_t.c.id).where(credentials_t.c.name == "default-bootstrap")
    ).fetchone()
    if default_cred is not None:
        default_credential_id = default_cred.id
    else:
        default_credential_id = uuid.uuid4()

        def _setting(key: str) -> str:
            row = bind.execute(
                sa.select(platform_settings_t.c.value).where(platform_settings_t.c.key == key)
            ).fetchone()
            return row.value if row is not None and row.value else ""

        default_username = _setting("ssh_bootstrap_username")
        default_secret_enc = _setting("ssh_bootstrap_password")  # Fernet ciphertext, copied verbatim

        bind.execute(
            credentials_t.insert().values(
                id=default_credential_id,
                name="default-bootstrap",
                kind="username_password",
                username=default_username,
                secret_enc=default_secret_enc,
            )
        )

    mapping_exists = bind.execute(
        sa.select(credential_groups_t.c.id).where(credential_groups_t.c.group_id == default_group_id)
    ).fetchone()
    if mapping_exists is None:
        bind.execute(
            credential_groups_t.insert().values(
                id=uuid.uuid4(),
                credential_id=default_credential_id,
                group_id=default_group_id,
                created_at=now,
            )
        )

    # NOTE (expand-contract): this is the *expand* phase. The embedded columns
    # groups.credential_id / nodes.credential_id are intentionally KEPT so all
    # existing callers keep working; the resolver reads credential_groups first
    # and falls back to the old columns. Orphan-node reassignment to the default
    # group and dropping the old columns happen in the later *contract* phase,
    # after every caller has moved to credential_groups.


def downgrade() -> None:
    """Additive-phase downgrade: drop the association table + its index.

    The old columns were never dropped in this phase, so there is nothing to
    restore there. The synthetic "default" group/credential are left in place
    (indistinguishable from operator data by downgrade time).
    """
    op.drop_index("idx_credential_groups_credential_id", table_name="credential_groups")
    op.drop_table("credential_groups")
