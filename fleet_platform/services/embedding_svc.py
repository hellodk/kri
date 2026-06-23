"""RAG knowledge-plane service.

Responsibilities:
1. Chunking: convert fleet sources into FleetEmbedding rows
2. Embedding: call nomic-embed-text-v1.5 via OpenAI-compat endpoint
3. Retrieval: hybrid BM25 (Postgres FTS) + pgvector cosine, RRF fusion
4. Context injection: format top-N chunks with [src: path/id] citations
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx
import yaml
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.fleet_embedding import FleetEmbedding

# Embedding contract — must match the Vector(768) column in fleet_embeddings (#575).
EXPECTED_EMBED_DIM = 768
EXPECTED_EMBED_MODEL = "nomic-embed-text-v1.5"

# nomic-embed-text-v1.5 task prefixes for asymmetric retrieval (#574).
_TASK_PREFIX = {
    "document": "search_document: ",
    "query": "search_query: ",
}

_DEFAULT_EMBED_BATCH_SIZE = 64
_EMBED_MAX_RETRIES = 3
_EMBED_TIMEOUT = 60.0


class EmbeddingDimensionError(RuntimeError):
    """Raised when the embed endpoint returns vectors whose dimension does not match
    the configured ``Vector(768)`` column — fail loud instead of writing junk (#575)."""


# --- Chunking helpers ---------------------------------------------------------


def compute_content_hash(text: str) -> str:
    """Return sha256 hex digest of text (64 hex chars)."""
    return hashlib.sha256(text.encode()).hexdigest()


def chunk_node(
    *,
    node_id: str,
    hostname: str,
    ip: str,
    status: str,
    group: str,
    os_info: str,
    last_seen: str,
    include_ips: bool = True,
) -> list[dict[str, Any]]:
    """One node = one chunk (profile card).

    Re-embed on: node registration, status change, group change.

    Privacy (#575): when ``include_ips`` is False the node IP is redacted at
    INGESTION — the address is never embedded nor shipped to the embed endpoint.
    This mirrors the chat-context redaction gate so sensitive data does not leak
    via the RAG plane when the embed endpoint is not trusted-local.
    """
    ip_display = ip if include_ips else "[REDACTED_IP]"
    body = (
        f"Node: {hostname}\n"
        f"ID: {node_id}\n"
        f"IP: {ip_display}\n"
        f"Status: {status}\n"
        f"Group: {group}\n"
        f"OS: {os_info}\n"
        f"Last seen: {last_seen}"
    )
    return [
        {
            "source_type": "node",
            "source_id": node_id,
            "chunk_text": f"[src: node/{hostname}] {body}",
            "content_hash": compute_content_hash(body),
            "metadata": {"hostname": hostname, "status": status, "group": group},
        }
    ]


def chunk_playbook(path: str, yaml_content: str) -> list[dict[str, Any]]:
    """One play = one chunk. Includes play name, hosts, task names."""
    try:
        plays = yaml.safe_load(yaml_content) or []
    except yaml.YAMLError:
        return []
    if not isinstance(plays, list):
        return []
    chunks = []
    for i, play in enumerate(plays):
        if not isinstance(play, dict):
            continue
        name = play.get("name", f"play_{i}")
        hosts = play.get("hosts", "all")
        tasks = play.get("tasks", [])
        task_names = [t.get("name", "") for t in tasks if isinstance(t, dict)]
        body = f"Playbook: {path}\nPlay: {name}\nHosts: {hosts}\nTasks: {', '.join(t for t in task_names if t)}"
        source_id = f"{path}:play_{i}"
        chunks.append(
            {
                "source_type": "playbook",
                "source_id": source_id,
                "chunk_text": f"[src: {source_id}] {body}",
                "content_hash": compute_content_hash(body),
                "metadata": {"path": path, "play_name": name, "hosts": hosts},
            }
        )
    return chunks


def chunk_salt_state(path: str, sls_content: str) -> list[dict[str, Any]]:
    """One top-level state ID = one chunk.

    SLS files are YAML; each top-level key is a state ID.
    Re-embed trigger: content_hash change (file watcher or Celery beat).
    """
    try:
        states = yaml.safe_load(sls_content) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(states, dict):
        return []
    chunks = []
    for state_id, body_val in states.items():
        body = f"Salt state: {path}\nID: {state_id}\nDeclaration: {str(body_val)[:400]}"
        source_id = f"{path}:{state_id}"
        chunks.append(
            {
                "source_type": "salt_state",
                "source_id": source_id,
                "chunk_text": f"[src: {source_id}] {body}",
                "content_hash": compute_content_hash(body),
                "metadata": {"path": path, "state_id": state_id},
            }
        )
    return chunks


def chunk_drift_record(
    *,
    drift_id: str,
    node_hostname: str,
    computed_at: str,
    drift_score: int,
    missing_packages: list,
    extra_packages: list,
    version_mismatches: list,
) -> list[dict[str, Any]]:
    """One drift record = one chunk. Captures findings as text."""
    findings = []
    for p in missing_packages[:10]:
        findings.append(f"missing: {p}")
    for p in extra_packages[:10]:
        findings.append(f"extra: {p}")
    for v in version_mismatches[:10]:
        findings.append(f"mismatch: {v}")
    body = f"Drift report for {node_hostname} at {computed_at}\nScore: {drift_score}\n" + "\n".join(findings)
    source_id = f"drift:{drift_id}"
    return [
        {
            "source_type": "drift",
            "source_id": source_id,
            "chunk_text": f"[src: {source_id}] {body}",
            "content_hash": compute_content_hash(body),
            "metadata": {
                "node_hostname": node_hostname,
                "drift_score": drift_score,
                "computed_at": computed_at,
            },
        }
    ]


# --- RRF fusion ---------------------------------------------------------------


def reciprocal_rank_fusion(
    bm25_ids: list[str],
    vector_ids: list[str],
    k: int = 60,
) -> list[str]:
    """Fuse two ranked lists via Reciprocal Rank Fusion.

    Each id scores 1/(k + rank) from each list. Deduplicates.
    Returns ids sorted by descending fused score.
    """
    scores: dict[str, float] = {}
    for ranked in (bm25_ids, vector_ids):
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda x: -scores[x])


# --- Embedding call -----------------------------------------------------------


def _apply_task_prefix(texts: list[str], mode: str | None) -> list[str]:
    """Prepend the nomic asymmetric-retrieval prefix for the given mode (#574).

    mode="document" at ingestion, mode="query" for search queries. Any other
    value (or None) leaves the text untouched (back-compat).
    """
    prefix = _TASK_PREFIX.get(mode or "", "")
    if not prefix:
        return list(texts)
    return [f"{prefix}{t}" for t in texts]


async def _post_embeddings(
    url: str,
    model: str,
    inputs: list[str],
    timeout: float,
) -> list[list[float]]:
    """Single POST to /v1/embeddings — isolated so batching/retry can wrap it."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json={"model": model, "input": inputs})
        resp.raise_for_status()
        data = resp.json()
    return [item["embedding"] for item in data["data"]]


async def embed_texts(
    texts: list[str],
    base_url: str,
    model: str = EXPECTED_EMBED_MODEL,
    *,
    mode: str | None = None,
    batch_size: int = _DEFAULT_EMBED_BATCH_SIZE,
    max_retries: int = _EMBED_MAX_RETRIES,
    timeout: float = _EMBED_TIMEOUT,
    expected_dim: int | None = EXPECTED_EMBED_DIM,
) -> list[list[float]]:
    """Call nomic-embed-text via OpenAI-compat /v1/embeddings endpoint.

    - Applies the nomic ``search_document:``/``search_query:`` prefix per ``mode`` (#574).
    - Batches large inputs (``batch_size``) so a big reindex never 413s/times out (#574).
    - Retries each batch with exponential backoff on transport errors (#574).
    - Validates returned dimension against ``expected_dim`` — raises
      ``EmbeddingDimensionError`` on mismatch so a wrong model/endpoint fails
      loud instead of corrupting the index (#575).

    Returns list of float vectors, one per input text. Raises httpx.HTTPError
    when all retries for a batch are exhausted.
    """
    if not texts:
        return []

    from fleet_platform.services.llm_caller import normalize_openai_base_url

    url = f"{normalize_openai_base_url(base_url)}/v1/embeddings"
    inputs = _apply_task_prefix(texts, mode)

    vectors: list[list[float]] = []
    for start in range(0, len(inputs), batch_size):
        batch = inputs[start : start + batch_size]
        attempt = 0
        while True:
            try:
                batch_vecs = await _post_embeddings(url, model, batch, timeout)
                break
            except httpx.HTTPError:
                attempt += 1
                if attempt >= max_retries:
                    raise
                await asyncio.sleep(min(2.0**attempt, 8.0))
        vectors.extend(batch_vecs)

    if expected_dim is not None:
        for vec in vectors:
            if len(vec) != expected_dim:
                raise EmbeddingDimensionError(
                    f"Embed endpoint returned {len(vec)}-dim vectors but the "
                    f"fleet_embeddings column is Vector({expected_dim}). Model "
                    f"'{model}' likely does not match the configured embed model. "
                    f"Check LLM_EMBED_BASE_URL and the served model."
                )

    return vectors


# --- Upsert -------------------------------------------------------------------


def plan_upsert(
    chunks: list[dict[str, Any]],
    existing: list[tuple[str, str | None]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Pure planner for a true upsert keyed on ``source_id`` (#573).

    ``existing`` is a list of ``(source_id, content_hash)`` rows already stored
    for the incoming source_ids. A source_id is considered *changed* when the set
    of stored content_hashes differs from the set of incoming content_hashes.

    Returns ``(delete_source_ids, insert_chunks)``:
      - ``delete_source_ids`` — source_ids whose stale rows must be removed
        before insert (delete-then-insert leaves exactly one current row set).
      - ``insert_chunks`` — chunks to (re-)embed and insert.
    Unchanged source_ids are skipped entirely (no delete, no re-embed).
    """
    incoming_by_sid: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        incoming_by_sid.setdefault(chunk["source_id"], []).append(chunk)

    existing_by_sid: dict[str, set[str | None]] = {}
    for sid, content_hash in existing:
        existing_by_sid.setdefault(sid, set()).add(content_hash)

    delete_sids: list[str] = []
    insert_chunks: list[dict[str, Any]] = []
    for sid, sid_chunks in incoming_by_sid.items():
        incoming_hashes: set[str | None] = {c["content_hash"] for c in sid_chunks}
        if existing_by_sid.get(sid, set()) != incoming_hashes:
            delete_sids.append(sid)
            insert_chunks.extend(sid_chunks)
    return delete_sids, insert_chunks


def plan_sweep(existing_source_ids: list[str], current_source_ids: list[str]) -> list[str]:
    """Pure planner for the orphan sweep (#573).

    Returns the source_ids present in storage but absent from the current set —
    i.e. embeddings for deleted nodes/playbooks that must be removed so the index
    never retains stale facts for sources that no longer exist.
    """
    current = set(current_source_ids)
    return [sid for sid in existing_source_ids if sid not in current]


async def upsert_chunks(
    db: AsyncSession,
    chunks: list[dict[str, Any]],
    embed_base_url: str,
) -> int:
    """Embed and upsert chunks into fleet_embeddings — TRUE upsert keyed on source_id (#573).

    For every source_id whose content changed, the stale rows are deleted and the
    new chunk(s) re-embedded and inserted, so a changed source leaves exactly one
    current row set. Unchanged source_ids are skipped (no re-embed).
    Returns count of inserted rows.
    """
    if not chunks:
        return 0

    source_ids = list({c["source_id"] for c in chunks})
    result = await db.execute(
        select(FleetEmbedding.source_id, FleetEmbedding.content_hash).where(FleetEmbedding.source_id.in_(source_ids))
    )
    existing = [(row[0], row[1]) for row in result.all()]

    delete_sids, insert_chunks = plan_upsert(chunks, existing)
    if not insert_chunks:
        return 0

    if delete_sids:
        await db.execute(
            delete(FleetEmbedding)
            .where(FleetEmbedding.source_id.in_(delete_sids))
            .execution_options(synchronize_session=False)
        )

    texts = [c["chunk_text"] for c in insert_chunks]
    vectors = await embed_texts(texts, embed_base_url, mode="document")

    now = datetime.now(UTC)
    for chunk, vector in zip(insert_chunks, vectors):
        row = FleetEmbedding(
            source_type=chunk["source_type"],
            source_id=chunk["source_id"],
            chunk_text=chunk["chunk_text"],
            embedding=vector,
            metadata_=chunk.get("metadata"),
            content_hash=chunk["content_hash"],
            embedded_at=now,
        )
        db.add(row)

    await db.commit()
    return len(insert_chunks)


async def sweep_deleted_sources(
    db: AsyncSession,
    source_type: str,
    current_source_ids: list[str],
) -> int:
    """Delete embeddings of ``source_type`` whose source_id is not in the current set (#573).

    Removes rows for nodes/playbooks that no longer exist so the index does not
    retain stale facts. Returns the number of rows deleted.
    """
    result = await db.execute(select(FleetEmbedding.source_id).where(FleetEmbedding.source_type == source_type))
    existing_source_ids = [row[0] for row in result.all()]
    to_delete = plan_sweep(existing_source_ids, current_source_ids)
    if not to_delete:
        return 0

    await db.execute(
        delete(FleetEmbedding)
        .where(
            FleetEmbedding.source_type == source_type,
            FleetEmbedding.source_id.in_(to_delete),
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return len(to_delete)


# --- Retrieval ----------------------------------------------------------------


async def retrieve(
    db: AsyncSession,
    query: str,
    embed_base_url: str,
    source_types: list[str] | None = None,
    top_k: int = 8,
    probes: int | None = None,
    ef_search: int | None = None,
) -> list[dict[str, Any]]:
    """Hybrid BM25 + pgvector retrieval with RRF fusion.

    Returns up to top_k chunks, each as
    {"chunk_text": str, "source_type": str, "source_id": str, "metadata": dict}
    ordered by fused relevance.

    ANN breadth is widened at query time (#574): ``ivfflat.probes`` (for an
    IVFFlat index) and ``hnsw.ef_search`` (for an HNSW index) are set via
    ``SET LOCAL`` so the vector scan visits multiple lists/neighbours instead of
    the single default list — both are harmless no-ops for the other index type.
    """
    from sqlalchemy import text

    # 1. BM25 via Postgres FTS (ts_rank)
    bm25_q = (
        select(
            FleetEmbedding.id,
            FleetEmbedding.chunk_text,
            FleetEmbedding.source_type,
            FleetEmbedding.source_id,
            FleetEmbedding.metadata_,
        )
        .where(text("tsv @@ plainto_tsquery('english', :q)"))
        .order_by(text("ts_rank(tsv, plainto_tsquery('english', :q)) DESC"))
        .limit(top_k * 2)
        .params(q=query)
    )
    if source_types:
        bm25_q = bm25_q.where(FleetEmbedding.source_type.in_(source_types))

    bm25_result = await db.execute(bm25_q)
    bm25_rows = bm25_result.all()
    bm25_ids = [str(r.id) for r in bm25_rows]

    # 2. Dense vector search (cosine distance) — query uses the nomic query prefix
    query_vec = (await embed_texts([query], embed_base_url, mode="query"))[0]

    # Widen ANN search breadth for this transaction. Values are ints we control,
    # so f-string interpolation is safe (SET does not accept bind parameters).
    probes_v = probes if probes is not None else max(10, top_k)
    ef_v = ef_search if ef_search is not None else max(40, top_k * 5)
    await db.execute(text(f"SET LOCAL ivfflat.probes = {int(probes_v)}"))
    await db.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_v)}"))

    vec_q = (
        select(
            FleetEmbedding.id,
            FleetEmbedding.chunk_text,
            FleetEmbedding.source_type,
            FleetEmbedding.source_id,
            FleetEmbedding.metadata_,
        )
        .order_by(FleetEmbedding.embedding.op("<=>")(query_vec))
        .limit(top_k * 2)
    )
    if source_types:
        vec_q = vec_q.where(FleetEmbedding.source_type.in_(source_types))

    vec_result = await db.execute(vec_q)
    vec_rows = vec_result.all()
    vector_ids = [str(r.id) for r in vec_rows]

    # 3. RRF fusion
    id_to_row = {str(r.id): r for r in (*bm25_rows, *vec_rows)}
    fused_ids = reciprocal_rank_fusion(bm25_ids, vector_ids)[:top_k]

    return [
        {
            "chunk_text": id_to_row[fid].chunk_text,
            "source_type": id_to_row[fid].source_type,
            "source_id": id_to_row[fid].source_id,
            "metadata": id_to_row[fid].metadata_,
        }
        for fid in fused_ids
        if fid in id_to_row
    ]


def format_retrieved_chunks(chunks: list[dict[str, Any]]) -> str:
    """Format top-N chunks for injection-safe insertion into the LLM context (#773).

    Each chunk is wrapped in explicit ``[chunk N]`` / ``[/chunk N]`` delimiters
    and its text is passed through :func:`sanitize_untrusted` before inclusion.
    This prevents stored-injection payloads (e.g. '## Rules' headings, code-fences,
    model-control tokens) embedded in playbook or Salt content from influencing
    the model's system-level behaviour.
    """
    if not chunks:
        return ""
    from fleet_platform.services.prompt_safety import sanitize_untrusted

    lines = ["[retrieved_knowledge]"]
    for i, c in enumerate(chunks, start=1):
        safe_text = sanitize_untrusted(c["chunk_text"])
        lines.append(f"[chunk {i}]")
        lines.append(safe_text)
        lines.append(f"[/chunk {i}]")
        lines.append("")
    lines.append("[/retrieved_knowledge]")
    return "\n".join(lines)
