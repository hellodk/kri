"""Integration tests for the RAG pipeline — requires real PostgreSQL with pgvector.

These tests use the db_session fixture from conftest.py (real AsyncSession).
The BM25 tests do not require the embedding endpoint — they insert FleetEmbedding rows
directly and query via Postgres FTS. The dense-vector tests skip if the embed URL is
absent.
"""
from datetime import UTC, datetime

import pytest


@pytest.mark.asyncio
async def test_bm25_retrieval_finds_inserted_chunk(db_session):
    """BM25 should find a chunk with matching keywords."""
    import uuid

    from sqlalchemy import text

    from fleet_platform.models.fleet_embedding import FleetEmbedding
    from fleet_platform.services.embedding_svc import compute_content_hash

    unique_token = f"fleetkeyword{uuid.uuid4().hex[:8]}"
    chunk_text = f"[src: node/mm1] Node: mm1 Status: online {unique_token}"
    content_hash = compute_content_hash(chunk_text)

    row = FleetEmbedding(
        source_type="node",
        source_id=f"test-bm25-{unique_token}",
        chunk_text=chunk_text,
        embedding=None,
        metadata_={"hostname": "mm1"},
        content_hash=content_hash,
        embedded_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.commit()

    # BM25 search via raw FTS query
    result = await db_session.execute(
        text(
            "SELECT id, chunk_text FROM fleet_embeddings "
            "WHERE tsv @@ plainto_tsquery('english', :q) "
            "ORDER BY ts_rank(tsv, plainto_tsquery('english', :q)) DESC "
            "LIMIT 5"
        ).bindparams(q=unique_token)
    )
    rows = result.fetchall()
    assert len(rows) >= 1
    assert any(unique_token in r.chunk_text for r in rows)

    # Cleanup
    await db_session.delete(row)
    await db_session.commit()


@pytest.mark.asyncio
async def test_upsert_skips_unchanged_chunk(db_session):
    """upsert_chunks must skip re-embedding when content_hash is unchanged."""
    import uuid
    from unittest.mock import AsyncMock, patch

    from fleet_platform.services.embedding_svc import (
        compute_content_hash,
        upsert_chunks,
    )

    unique_id = f"test-skip-{uuid.uuid4().hex[:8]}"
    chunk_text = f"[src: node/{unique_id}] Node: {unique_id} Status: online"
    chunk = {
        "source_type": "node",
        "source_id": unique_id,
        "chunk_text": chunk_text,
        "content_hash": compute_content_hash(chunk_text),
        "metadata": {"hostname": unique_id},
    }

    fake_vector = [0.1] * 768

    with patch(
        "fleet_platform.services.embedding_svc.embed_texts",
        new_callable=AsyncMock,
        return_value=[fake_vector],
    ):
        count1 = await upsert_chunks(db_session, [chunk], "http://fake-embed-url")
    assert count1 == 1

    # Record embedded_at of the inserted row
    from sqlalchemy import select

    from fleet_platform.models.fleet_embedding import FleetEmbedding

    result = await db_session.execute(
        select(FleetEmbedding).where(FleetEmbedding.source_id == unique_id)
    )
    inserted = result.scalar_one()
    original_embedded_at = inserted.embedded_at

    # Upsert same chunk again — should skip (hash unchanged)
    with patch(
        "fleet_platform.services.embedding_svc.embed_texts",
        new_callable=AsyncMock,
        return_value=[fake_vector],
    ) as mock_embed:
        count2 = await upsert_chunks(db_session, [chunk], "http://fake-embed-url")

    assert count2 == 0
    mock_embed.assert_not_called()

    # embedded_at must be unchanged
    await db_session.refresh(inserted)
    assert inserted.embedded_at == original_embedded_at

    # Cleanup
    await db_session.delete(inserted)
    await db_session.commit()


@pytest.mark.asyncio
async def test_content_hash_triggers_reembed(db_session):
    """upsert_chunks must re-embed when chunk_text changes."""
    import uuid
    from unittest.mock import AsyncMock, patch

    from fleet_platform.services.embedding_svc import (
        compute_content_hash,
        upsert_chunks,
    )

    unique_id = f"test-rehash-{uuid.uuid4().hex[:8]}"
    chunk_v1_text = f"[src: node/{unique_id}] Node: {unique_id} Status: online"
    chunk_v1 = {
        "source_type": "node",
        "source_id": unique_id,
        "chunk_text": chunk_v1_text,
        "content_hash": compute_content_hash(chunk_v1_text),
        "metadata": {},
    }

    fake_vector = [0.1] * 768

    with patch(
        "fleet_platform.services.embedding_svc.embed_texts",
        new_callable=AsyncMock,
        return_value=[fake_vector],
    ):
        await upsert_chunks(db_session, [chunk_v1], "http://fake-embed-url")

    from sqlalchemy import select

    from fleet_platform.models.fleet_embedding import FleetEmbedding

    result = await db_session.execute(
        select(FleetEmbedding).where(FleetEmbedding.source_id == unique_id)
    )
    inserted_v1 = result.scalar_one()
    _embedded_at_v1 = inserted_v1.embedded_at  # captured for potential future assertion

    # Change chunk text — hash changes
    chunk_v2_text = f"[src: node/{unique_id}] Node: {unique_id} Status: offline"
    chunk_v2 = {
        "source_type": "node",
        "source_id": unique_id,
        "chunk_text": chunk_v2_text,
        "content_hash": compute_content_hash(chunk_v2_text),
        "metadata": {},
    }
    assert chunk_v2["content_hash"] != chunk_v1["content_hash"]

    with patch(
        "fleet_platform.services.embedding_svc.embed_texts",
        new_callable=AsyncMock,
        return_value=[fake_vector],
    ) as mock_embed:
        count2 = await upsert_chunks(db_session, [chunk_v2], "http://fake-embed-url")

    assert count2 == 1
    mock_embed.assert_called_once()

    # Cleanup both rows
    result2 = await db_session.execute(
        select(FleetEmbedding).where(FleetEmbedding.source_id == unique_id)
    )
    for row in result2.scalars().all():
        await db_session.delete(row)
    await db_session.commit()


@pytest.mark.asyncio
async def test_rrf_fusion_deduplication(db_session):
    """RRF fusion must never return duplicate ids."""
    from fleet_platform.services.embedding_svc import reciprocal_rank_fusion

    fused = reciprocal_rank_fusion(["a", "b", "c"], ["b", "a", "d"])
    assert len(fused) == len(set(fused))
    assert fused[0] in ("a", "b")
    assert fused[1] in ("a", "b")
