"""Unit tests for the RAG overhaul (#573 reindex routing + true upsert/sweep,
#574 nomic prefixes + ANN probes + batch/retry/dim, #575 ingestion redaction +
grounding pinning + eval harness).

Every regression test here is written to FAIL against the pre-fix behaviour.
"""

import json
import pathlib
from unittest.mock import AsyncMock

import httpx
import pytest


# --------------------------------------------------------------------------- #
# #573 — reindex tasks routed to a worker-consumed queue
# --------------------------------------------------------------------------- #
def test_reindex_tasks_routed_to_consumed_queue():
    from fleet_platform.workers.celery_app import celery_app

    consumed = {"default", "maintenance", "drift", "sbom"}
    routes = celery_app.conf.task_routes
    matches = [v for pat, v in routes.items() if "embedding_tasks" in pat]
    assert matches, "embedding_tasks.* must have a task_routes entry (pre-fix: fell to unconsumed 'celery')"
    assert all(m["queue"] in consumed for m in matches), (
        f"reindex tasks must route to a consumed queue {consumed}, got {matches}"
    )


# --------------------------------------------------------------------------- #
# #573 — true upsert keyed on source_id + orphan sweep (pure planners)
# --------------------------------------------------------------------------- #
def _node_chunk(source_id: str, content_hash: str) -> dict:
    return {
        "source_type": "node",
        "source_id": source_id,
        "chunk_text": f"[src: node/{source_id}] body {content_hash}",
        "content_hash": content_hash,
        "metadata": {},
    }


def test_plan_upsert_replaces_changed_source_not_duplicate():
    from fleet_platform.services.embedding_svc import plan_upsert

    incoming = [_node_chunk("n1", "newhash")]
    existing = [("n1", "oldhash")]  # stored row has different hash
    delete_sids, insert_chunks = plan_upsert(incoming, existing)
    assert delete_sids == ["n1"], "changed source must delete its stale row before insert"
    assert len(insert_chunks) == 1 and insert_chunks[0]["content_hash"] == "newhash"


def test_plan_upsert_skips_unchanged_source():
    from fleet_platform.services.embedding_svc import plan_upsert

    incoming = [_node_chunk("n1", "samehash")]
    existing = [("n1", "samehash")]
    delete_sids, insert_chunks = plan_upsert(incoming, existing)
    assert delete_sids == []
    assert insert_chunks == []


def test_plan_sweep_removes_deleted_sources():
    from fleet_platform.services.embedding_svc import plan_sweep

    stored = ["n1", "n2", "n3-deleted"]
    current = ["n1", "n2"]
    assert plan_sweep(stored, current) == ["n3-deleted"]


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeUpsertSession:
    """Records add()/DELETE/commit; returns preset rows for the SELECT."""

    def __init__(self, existing):
        self._existing = existing
        self.added = []
        self.deletes = []
        self.committed = False

    async def execute(self, stmt, *a, **k):
        sql = str(stmt).lstrip().upper()
        if sql.startswith("SELECT"):
            return _FakeResult(self._existing)
        if sql.startswith("DELETE"):
            self.deletes.append(str(stmt))
            return _FakeResult([])
        return _FakeResult([])

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_upsert_chunks_changed_source_deletes_then_inserts(monkeypatch):
    from fleet_platform.services import embedding_svc

    monkeypatch.setattr(embedding_svc, "embed_texts", AsyncMock(return_value=[[0.1] * 768]))
    session = _FakeUpsertSession(existing=[("n1", "oldhash")])
    count = await embedding_svc.upsert_chunks(session, [_node_chunk("n1", "newhash")], "http://embed")

    assert count == 1
    assert len(session.deletes) == 1, "stale row for changed source must be deleted (true upsert)"
    assert len(session.added) == 1, "exactly one current row inserted"


@pytest.mark.asyncio
async def test_upsert_chunks_unchanged_source_no_embed_no_write(monkeypatch):
    from fleet_platform.services import embedding_svc

    embed = AsyncMock(return_value=[[0.1] * 768])
    monkeypatch.setattr(embedding_svc, "embed_texts", embed)
    session = _FakeUpsertSession(existing=[("n1", "samehash")])
    count = await embedding_svc.upsert_chunks(session, [_node_chunk("n1", "samehash")], "http://embed")

    assert count == 0
    embed.assert_not_called()
    assert session.added == []
    assert session.deletes == []


@pytest.mark.asyncio
async def test_sweep_deleted_sources_removes_orphans():
    from fleet_platform.services import embedding_svc

    session = _FakeUpsertSession(existing=[("n1",), ("n2",), ("n-old",)])
    removed = await embedding_svc.sweep_deleted_sources(session, "node", ["n1", "n2"])
    assert removed == 1
    assert len(session.deletes) == 1
    assert session.committed is True


# --------------------------------------------------------------------------- #
# #574 — nomic task prefixes
# --------------------------------------------------------------------------- #
def test_task_prefix_document_vs_query():
    from fleet_platform.services.embedding_svc import _apply_task_prefix

    assert _apply_task_prefix(["hi"], "document") == ["search_document: hi"]
    assert _apply_task_prefix(["hi"], "query") == ["search_query: hi"]
    assert _apply_task_prefix(["hi"], None) == ["hi"]


@pytest.mark.asyncio
async def test_embed_texts_applies_document_and_query_prefix(monkeypatch):
    from fleet_platform.services import embedding_svc

    captured = []

    async def _fake_post(url, model, inputs, timeout):
        captured.append(list(inputs))
        return [[0.0] * 768 for _ in inputs]

    monkeypatch.setattr(embedding_svc, "_post_embeddings", _fake_post)

    await embedding_svc.embed_texts(["hello"], "http://embed", mode="document")
    await embedding_svc.embed_texts(["hello"], "http://embed", mode="query")

    assert captured[0] == ["search_document: hello"]
    assert captured[1] == ["search_query: hello"]


# --------------------------------------------------------------------------- #
# #574 — batching + retry + dimension validation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_embed_texts_batches_large_input(monkeypatch):
    from fleet_platform.services import embedding_svc

    sizes = []

    async def _fake_post(url, model, inputs, timeout):
        sizes.append(len(inputs))
        return [[0.0] * 768 for _ in inputs]

    monkeypatch.setattr(embedding_svc, "_post_embeddings", _fake_post)
    texts = [f"t{i}" for i in range(130)]
    out = await embedding_svc.embed_texts(texts, "http://embed", batch_size=64)
    assert len(out) == 130
    assert sizes == [64, 64, 2], "large input must be split into batches"


@pytest.mark.asyncio
async def test_embed_texts_retries_on_transport_error(monkeypatch):
    from fleet_platform.services import embedding_svc

    monkeypatch.setattr(embedding_svc.asyncio, "sleep", AsyncMock())
    calls = {"n": 0}

    async def _flaky_post(url, model, inputs, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return [[0.0] * 768 for _ in inputs]

    monkeypatch.setattr(embedding_svc, "_post_embeddings", _flaky_post)
    out = await embedding_svc.embed_texts(["t"], "http://embed", max_retries=3)
    assert len(out) == 1
    assert calls["n"] == 2, "must retry once then succeed"


@pytest.mark.asyncio
async def test_embed_texts_raises_on_dimension_mismatch(monkeypatch):
    from fleet_platform.services import embedding_svc

    async def _bad_dim(url, model, inputs, timeout):
        return [[0.0, 0.0, 0.0] for _ in inputs]  # 3-dim, not 768

    monkeypatch.setattr(embedding_svc, "_post_embeddings", _bad_dim)
    with pytest.raises(embedding_svc.EmbeddingDimensionError):
        await embedding_svc.embed_texts(["t"], "http://embed")


# --------------------------------------------------------------------------- #
# #574 — probes set on retrieve
# --------------------------------------------------------------------------- #
class _FakeRetrieveSession:
    def __init__(self):
        self.statements = []

    async def execute(self, stmt, *a, **k):
        self.statements.append(str(stmt))
        return _FakeResult([])


@pytest.mark.asyncio
async def test_retrieve_sets_ann_probes(monkeypatch):
    from fleet_platform.services import embedding_svc

    monkeypatch.setattr(embedding_svc, "embed_texts", AsyncMock(return_value=[[0.1] * 768]))
    session = _FakeRetrieveSession()
    await embedding_svc.retrieve(session, "find mm1", "http://embed", top_k=6)

    joined = " ".join(session.statements)
    assert "ivfflat.probes" in joined, "retrieve must SET LOCAL ivfflat.probes to widen ANN search"
    assert "hnsw.ef_search" in joined, "retrieve must SET LOCAL hnsw.ef_search for HNSW index"


# --------------------------------------------------------------------------- #
# #575 — ingestion redaction
# --------------------------------------------------------------------------- #
def test_chunk_node_redacts_ip_at_ingestion():
    from fleet_platform.services.embedding_svc import chunk_node

    chunks = chunk_node(
        node_id="n1",
        hostname="mm1",
        ip="192.168.1.50",
        status="online",
        group="build",
        os_info="",
        last_seen="2m ago",
        include_ips=False,
    )
    assert "192.168.1.50" not in chunks[0]["chunk_text"], "IP must be redacted at ingestion"
    assert "[REDACTED_IP]" in chunks[0]["chunk_text"]


def test_chunk_node_includes_ip_when_allowed():
    from fleet_platform.services.embedding_svc import chunk_node

    chunks = chunk_node(
        node_id="n1",
        hostname="mm1",
        ip="192.168.1.50",
        status="online",
        group="build",
        os_info="",
        last_seen="2m ago",
        include_ips=True,
    )
    assert "192.168.1.50" in chunks[0]["chunk_text"]


# --------------------------------------------------------------------------- #
# #575 — grounding rules pinned last + never truncated
# --------------------------------------------------------------------------- #
def test_grounding_rules_after_task_addendum_and_last():
    from fleet_platform.services.llm_context import _GROUNDING_RULES, build_static_context

    ctx = build_static_context(
        node_count=1,
        online_count=1,
        groups=["build"],
        salt_master="",
        playbooks_dir="",
        retrieved_chunks="x" * 5000,
        task_addendum="UNIQUE_TASK_MARKER_123",
    )
    assert ctx.index("UNIQUE_TASK_MARKER_123") < ctx.index("AUTHORITATIVE"), (
        "grounding rules must come AFTER the task addendum"
    )
    assert ctx.rstrip().endswith(_GROUNDING_RULES.rstrip()), "grounding rules must be the very last text"


def test_truncate_system_prompt_preserves_grounding_tail():
    from fleet_platform.services.llm_caller import _truncate_system_prompt

    middle = "RETRIEVED CHUNK FILLER. " * 2000
    grounding = (
        "## Rules\n- Prefer idempotent operations.\n"
        "- Answer ONLY from the Fleet Snapshot. Never claim to have performed a live action.\n"
    )
    prompt = "HEAD: you are kri assistant.\n" + middle + grounding
    out = _truncate_system_prompt(prompt, max_system_chars=1200)

    assert len(out) <= 1200 + 100  # marker overhead
    assert "## Rules" in out, "grounding/rules block must survive truncation"
    assert "Never claim to have performed a live action." in out
    assert "context truncated" in out


# --------------------------------------------------------------------------- #
# #575 — retrieval-quality eval harness on golden fixture
# --------------------------------------------------------------------------- #
def _load_golden():
    path = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "rag_golden.json"
    return json.loads(path.read_text())


def test_eval_harness_recall_at_k_on_golden_fixture():
    from fleet_platform.services.rag_eval import recall_at_k

    g = _load_golden()
    recall = recall_at_k(g["corpus"], g["queries"], k=3)
    assert recall >= 0.8, f"recall@3 regressed below 0.8: {recall}"


def test_eval_harness_groundedness_on_golden_fixture():
    from fleet_platform.services.rag_eval import groundedness

    g = _load_golden()
    grounded = groundedness(g["corpus"], g["queries"], k=3)
    assert grounded == 1.0, f"retriever surfaced a source not in the corpus: groundedness={grounded}"
