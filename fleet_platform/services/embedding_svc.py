"""RAG knowledge-plane service.

Responsibilities:
1. Chunking: convert fleet sources into FleetEmbedding rows
2. Embedding: call nomic-embed-text-v1.5 via OpenAI-compat endpoint
3. Retrieval: hybrid BM25 (Postgres FTS) + pgvector cosine, RRF fusion
4. Context injection: format top-N chunks with [src: path/id] citations
"""
import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.fleet_embedding import FleetEmbedding


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
) -> list[dict[str, Any]]:
    """One node = one chunk (profile card).

    Re-embed on: node registration, status change, group change.
    """
    body = (
        f"Node: {hostname}\n"
        f"ID: {node_id}\n"
        f"IP: {ip}\n"
        f"Status: {status}\n"
        f"Group: {group}\n"
        f"OS: {os_info}\n"
        f"Last seen: {last_seen}"
    )
    return [{
        "source_type": "node",
        "source_id": node_id,
        "chunk_text": f"[src: node/{hostname}] {body}",
        "content_hash": compute_content_hash(body),
        "metadata": {"hostname": hostname, "status": status, "group": group},
    }]


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
        body = (
            f"Playbook: {path}\n"
            f"Play: {name}\n"
            f"Hosts: {hosts}\n"
            f"Tasks: {', '.join(t for t in task_names if t)}"
        )
        source_id = f"{path}:play_{i}"
        chunks.append({
            "source_type": "playbook",
            "source_id": source_id,
            "chunk_text": f"[src: {source_id}] {body}",
            "content_hash": compute_content_hash(body),
            "metadata": {"path": path, "play_name": name, "hosts": hosts},
        })
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
        chunks.append({
            "source_type": "salt_state",
            "source_id": source_id,
            "chunk_text": f"[src: {source_id}] {body}",
            "content_hash": compute_content_hash(body),
            "metadata": {"path": path, "state_id": state_id},
        })
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
    body = (
        f"Drift report for {node_hostname} at {computed_at}\n"
        f"Score: {drift_score}\n"
        + "\n".join(findings)
    )
    source_id = f"drift:{drift_id}"
    return [{
        "source_type": "drift",
        "source_id": source_id,
        "chunk_text": f"[src: {source_id}] {body}",
        "content_hash": compute_content_hash(body),
        "metadata": {
            "node_hostname": node_hostname,
            "drift_score": drift_score,
            "computed_at": computed_at,
        },
    }]


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

async def embed_texts(
    texts: list[str],
    base_url: str,
    model: str = "nomic-embed-text-v1.5",
) -> list[list[float]]:
    """Call nomic-embed-text via OpenAI-compat /v1/embeddings endpoint.

    Returns list of 768-dim float vectors, one per input text.
    Raises httpx.HTTPError on failure.
    """
    from fleet_platform.services.llm_caller import normalize_openai_base_url
    url = f"{normalize_openai_base_url(base_url)}/v1/embeddings"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json={"model": model, "input": texts})
        resp.raise_for_status()
        data = resp.json()
    return [item["embedding"] for item in data["data"]]


# --- Upsert -------------------------------------------------------------------

async def upsert_chunks(
    db: AsyncSession,
    chunks: list[dict[str, Any]],
    embed_base_url: str,
) -> int:
    """Embed and upsert chunks into fleet_embeddings.

    Skips chunks whose content_hash already exists (unchanged).
    Returns count of new/updated rows.
    """
    if not chunks:
        return 0

    # Check which hashes already exist
    hashes = [c["content_hash"] for c in chunks]
    result = await db.execute(
        select(FleetEmbedding.content_hash).where(
            FleetEmbedding.content_hash.in_(hashes)
        )
    )
    existing_hashes = {row[0] for row in result.all()}

    new_chunks = [c for c in chunks if c["content_hash"] not in existing_hashes]
    if not new_chunks:
        return 0

    texts = [c["chunk_text"] for c in new_chunks]
    vectors = await embed_texts(texts, embed_base_url)

    now = datetime.now(UTC)
    for chunk, vector in zip(new_chunks, vectors):
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
    return len(new_chunks)


# --- Retrieval ----------------------------------------------------------------

async def retrieve(
    db: AsyncSession,
    query: str,
    embed_base_url: str,
    source_types: list[str] | None = None,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Hybrid BM25 + pgvector retrieval with RRF fusion.

    Returns up to top_k chunks, each as
    {"chunk_text": str, "source_type": str, "source_id": str, "metadata": dict}
    ordered by fused relevance.
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

    # 2. Dense vector search (cosine distance)
    query_vec = (await embed_texts([query], embed_base_url))[0]
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
    """Format top-N chunks for insertion into the LLM context block."""
    if not chunks:
        return ""
    lines = ["## Retrieved Knowledge\n"]
    for c in chunks:
        lines.append(c["chunk_text"])
        lines.append("")
    return "\n".join(lines)
