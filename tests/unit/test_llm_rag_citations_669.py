"""Tests for RAG citation assembly, silent-failure logging, and model validation (#669)."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.services.embedding_svc import (
    EXPECTED_EMBED_MODEL,
    assemble_citations,
    validate_embed_model,
)

# ---------------------------------------------------------------------------
# assemble_citations
# ---------------------------------------------------------------------------


def test_assemble_citations_returns_structured_list():
    chunks = [
        {"source_type": "node", "source_id": "node/mm1", "chunk_text": "..."},
        {"source_type": "playbook", "source_id": "playbooks/deploy.yml:play_0", "chunk_text": "..."},
    ]
    citations = assemble_citations(chunks)
    assert len(citations) == 2
    assert citations[0] == {"source_type": "node", "source_id": "node/mm1"}
    assert citations[1] == {"source_type": "playbook", "source_id": "playbooks/deploy.yml:play_0"}


def test_assemble_citations_deduplicates():
    chunks = [
        {"source_type": "node", "source_id": "node/mm1", "chunk_text": "a"},
        {"source_type": "node", "source_id": "node/mm1", "chunk_text": "b"},
        {"source_type": "playbook", "source_id": "play/x.yml:play_0", "chunk_text": "c"},
    ]
    citations = assemble_citations(chunks)
    assert len(citations) == 2
    source_ids = [c["source_id"] for c in citations]
    assert source_ids.count("node/mm1") == 1


def test_assemble_citations_empty_input():
    assert assemble_citations([]) == []


def test_assemble_citations_preserves_rank_order():
    chunks = [
        {"source_type": "drift", "source_id": "drift:a", "chunk_text": ""},
        {"source_type": "node", "source_id": "node/b", "chunk_text": ""},
        {"source_type": "salt_state", "source_id": "states/c.sls:id", "chunk_text": ""},
    ]
    citations = assemble_citations(chunks)
    assert [c["source_id"] for c in citations] == ["drift:a", "node/b", "states/c.sls:id"]


def test_assemble_citations_skips_empty_source_id():
    chunks = [
        {"source_type": "node", "source_id": "", "chunk_text": "no id"},
        {"source_type": "playbook", "source_id": "play/ok.yml:play_0", "chunk_text": "ok"},
    ]
    citations = assemble_citations(chunks)
    assert len(citations) == 1
    assert citations[0]["source_id"] == "play/ok.yml:play_0"


# ---------------------------------------------------------------------------
# validate_embed_model
# ---------------------------------------------------------------------------


def test_validate_embed_model_passes_for_correct_model():
    validate_embed_model(EXPECTED_EMBED_MODEL)  # must not raise


def test_validate_embed_model_raises_for_wrong_model():
    with pytest.raises(ValueError, match="Embed model mismatch"):
        validate_embed_model("wrong-model-v1")


def test_validate_embed_model_error_mentions_expected():
    with pytest.raises(ValueError, match=EXPECTED_EMBED_MODEL):
        validate_embed_model("llama3")


# ---------------------------------------------------------------------------
# build_fleet_context: silent-failure now logs a warning (not swallowed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_fleet_context_logs_rag_failure(caplog):
    """RAG retrieval errors must be logged at WARNING level, not silently dropped."""
    from fleet_platform.services import llm_context

    db = AsyncMock()

    # Mock all DB queries to return minimal valid data
    def make_result(scalars_val=None, scalar_val=None, all_val=None):
        r = MagicMock()
        r.scalar_one.return_value = scalar_val if scalar_val is not None else 0
        r.scalars.return_value.all.return_value = scalars_val if scalars_val is not None else []
        r.all.return_value = all_val if all_val is not None else []
        return r

    db.execute = AsyncMock(
        side_effect=[
            make_result(scalar_val=3),  # node_count
            make_result(scalar_val=2),  # online_count
            make_result(scalars_val=[]),  # groups
            make_result(all_val=[]),  # node rows
            make_result(all_val=[]),  # membership
        ]
    )

    settings_patch = {
        "salt_master_address": "salt-master.local",
        "playbooks_dir": "/srv/playbooks",
        "llm_include_node_ips": "true",
        "llm_embed_base_url": "http://embed.local",
    }

    with (
        patch(
            "fleet_platform.services.platform_settings_svc.get_settings_bulk",
            new=AsyncMock(return_value=settings_patch),
        ),
        patch(
            "fleet_platform.services.embedding_svc.retrieve",
            new=AsyncMock(side_effect=RuntimeError("embed endpoint unreachable")),
        ),
        caplog.at_level(logging.WARNING, logger="fleet_platform.services.llm_context"),
    ):
        context, citations = await llm_context.build_fleet_context(db, "fleet_query", query="which nodes are online")

    assert isinstance(context, str)
    assert citations == []
    assert any("RAG retrieval failed" in r.message for r in caplog.records), (
        "Expected a WARNING about RAG retrieval failure but got: " + str([r.message for r in caplog.records])
    )


@pytest.mark.asyncio
async def test_build_fleet_context_returns_citations_on_success():
    """build_fleet_context returns citation list alongside the context string."""
    from fleet_platform.services import llm_context

    db = AsyncMock()

    def make_result(scalars_val=None, scalar_val=None, all_val=None):
        r = MagicMock()
        r.scalar_one.return_value = scalar_val if scalar_val is not None else 0
        r.scalars.return_value.all.return_value = scalars_val if scalars_val is not None else []
        r.all.return_value = all_val if all_val is not None else []
        return r

    db.execute = AsyncMock(
        side_effect=[
            make_result(scalar_val=1),
            make_result(scalar_val=1),
            make_result(scalars_val=[]),
            make_result(all_val=[]),
            make_result(all_val=[]),
        ]
    )

    fake_chunks = [
        {"source_type": "node", "source_id": "node/mm1", "chunk_text": "[src: node/mm1] Node: mm1", "metadata": {}},
    ]

    settings_patch = {
        "salt_master_address": "",
        "playbooks_dir": "",
        "llm_include_node_ips": "true",
        "llm_embed_base_url": "http://embed.local",
    }

    with (
        patch(
            "fleet_platform.services.platform_settings_svc.get_settings_bulk",
            new=AsyncMock(return_value=settings_patch),
        ),
        patch(
            "fleet_platform.services.embedding_svc.retrieve",
            new=AsyncMock(return_value=fake_chunks),
        ),
    ):
        context, citations = await llm_context.build_fleet_context(db, "fleet_query", query="status of mm1")

    assert isinstance(context, str)
    assert len(citations) == 1
    assert citations[0] == {"source_type": "node", "source_id": "node/mm1"}
