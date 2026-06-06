"""Unit tests for FleetEmbedding model — issue #400.

Verifies the source/model contract: FleetEmbedding must declare the 'tsv'
generated tsvector column matching migration 032_fleet_embeddings.py.
"""

from sqlalchemy.dialects.postgresql import TSVECTOR

from fleet_platform.models.base import Base
from fleet_platform.models.fleet_embedding import FleetEmbedding


def test_fleet_embedding_has_tsv_attribute():
    """FleetEmbedding must expose a 'tsv' attribute on the mapper."""
    assert hasattr(FleetEmbedding, "tsv"), "FleetEmbedding is missing the 'tsv' mapped attribute"


def test_tsv_column_is_tsvector():
    """The 'tsv' column must be of type TSVECTOR."""
    col = FleetEmbedding.__table__.c["tsv"]
    assert isinstance(col.type, TSVECTOR), f"Expected TSVECTOR, got {type(col.type)}"


def test_tsv_column_is_computed():
    """The 'tsv' column must be a server-side GENERATED ALWAYS computed column."""
    col = FleetEmbedding.__table__.c["tsv"]
    assert col.computed is not None, "'tsv' column is not a Computed (generated) column"


def test_tsv_computed_sql_contains_tsvector_expression():
    """The Computed expression must reference to_tsvector('english', chunk_text)."""
    col = FleetEmbedding.__table__.c["tsv"]
    sql_text = str(col.computed.sqltext)
    assert "to_tsvector" in sql_text, f"Expected to_tsvector in computed SQL, got: {sql_text!r}"
    assert "english" in sql_text, f"Expected 'english' language in computed SQL, got: {sql_text!r}"
    assert "chunk_text" in sql_text, f"Expected 'chunk_text' in computed SQL, got: {sql_text!r}"


def test_tsv_computed_is_persisted():
    """The computed column must be persisted=True (STORED), matching the migration."""
    col = FleetEmbedding.__table__.c["tsv"]
    assert col.computed.persisted is True, "'tsv' computed column must be persisted (STORED)"


def test_fleet_embeddings_table_in_metadata():
    """fleet_embeddings table must appear in Base.metadata with the tsv column."""
    table = Base.metadata.tables.get("fleet_embeddings")
    assert table is not None, "'fleet_embeddings' table not found in Base.metadata"
    assert "tsv" in table.c, "'tsv' column missing from fleet_embeddings table in Base.metadata"
