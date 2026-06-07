"""Replace empty-trained IVFFlat with HNSW for fleet_embeddings ANN search (#574).

The original IVFFlat index (migration 032) was created on an EMPTY table, so its
centroids were trained on zero rows — recall collapses regardless of query-time
``ivfflat.probes``. HNSW needs no training data, builds incrementally as rows are
inserted, and gives strong recall on a growing table. Query-time breadth is tuned
via ``hnsw.ef_search`` (set in embedding_svc.retrieve).
"""

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the untrained IVFFlat index created in migration 032.
    op.execute("DROP INDEX IF EXISTS fleet_embeddings_embedding_idx")
    # HNSW index — training-free, incremental, good recall on a growing table.
    op.execute(
        "CREATE INDEX IF NOT EXISTS fleet_embeddings_embedding_hnsw_idx "
        "ON fleet_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS fleet_embeddings_embedding_hnsw_idx")
    op.execute(
        "CREATE INDEX IF NOT EXISTS fleet_embeddings_embedding_idx "
        "ON fleet_embeddings USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 50)"
    )
