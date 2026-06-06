"""Add pgvector extension and fleet_embeddings table for RAG pipeline (#263)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension — requires PostgreSQL superuser or pg_extension privilege
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "fleet_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(256), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        # created as text first; re-typed to vector(768) after extension is active
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Re-type the embedding column to vector(768) now that the extension exists
    op.execute("ALTER TABLE fleet_embeddings ALTER COLUMN embedding TYPE vector(768) USING NULL")
    # IVFFlat index for ANN cosine search (lists=50 suitable for ≤50k chunks)
    op.execute(
        "CREATE INDEX fleet_embeddings_embedding_idx "
        "ON fleet_embeddings USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 50)"
    )
    # Generated tsvector column for BM25 hybrid search
    op.execute(
        "ALTER TABLE fleet_embeddings "
        "ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED"
    )
    # GIN index on tsvector
    op.execute("CREATE INDEX fleet_embeddings_tsv_idx ON fleet_embeddings USING gin (tsv)")
    op.create_index("idx_fleet_embeddings_source", "fleet_embeddings", ["source_type", "source_id"])
    op.create_index("idx_fleet_embeddings_hash", "fleet_embeddings", ["content_hash"])


def downgrade() -> None:
    op.drop_index("idx_fleet_embeddings_hash", table_name="fleet_embeddings")
    op.drop_index("idx_fleet_embeddings_source", table_name="fleet_embeddings")
    op.drop_table("fleet_embeddings")
    # Do NOT drop the vector extension — other tables may use it
