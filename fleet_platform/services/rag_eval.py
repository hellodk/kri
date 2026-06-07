"""Retrieval-quality eval harness — recall@k + groundedness (RAG regression gate, #575).

Before this, only hash-dedup/RRF unit tests existed; any chunking/model/top-k change
shipped blind. This harness scores a golden query -> expected-source fixture against
the SAME fusion logic used in production (``reciprocal_rank_fusion``) so changes to the
retrieval glue are caught.

It is deliberately self-contained and DB-free: BM25 is a token-overlap proxy and the
default embedder is a deterministic TF vector. An ``embed_fn`` hook lets callers plug a
real embedder. The harness gates the chunking + dual-signal + fusion + top-k logic.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable

from fleet_platform.services.embedding_svc import reciprocal_rank_fusion

# corpus item: {"source_id": str, "chunk_text": str}
# query item:  {"query": str, "expected_source_ids": list[str]}
EmbedFn = Callable[[str], "Counter[str]"]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def default_embed_fn(text: str) -> Counter[str]:
    """Deterministic bag-of-words TF vector — stand-in for the real embedder."""
    return Counter(_tokenize(text))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(weight * b.get(tok, 0) for tok, weight in a.items())
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _bm25_rank(query: str, corpus: list[dict]) -> list[str]:
    """Token-overlap proxy for the Postgres FTS BM25 signal."""
    q_tokens = set(_tokenize(query))
    scored: list[tuple[int, str]] = []
    for item in corpus:
        overlap = sum(1 for tok in _tokenize(item["chunk_text"]) if tok in q_tokens)
        if overlap:
            scored.append((overlap, item["source_id"]))
    scored.sort(key=lambda x: -x[0])
    return [sid for _, sid in scored]


def _vector_rank(query: str, corpus: list[dict], embed_fn: EmbedFn) -> list[str]:
    q_vec = embed_fn(query)
    scored: list[tuple[float, str]] = []
    for item in corpus:
        sim = _cosine(q_vec, embed_fn(item["chunk_text"]))
        if sim > 0.0:
            scored.append((sim, item["source_id"]))
    scored.sort(key=lambda x: -x[0])
    return [sid for _, sid in scored]


def retrieve_offline(
    query: str,
    corpus: list[dict],
    top_k: int = 8,
    embed_fn: EmbedFn | None = None,
) -> list[str]:
    """Hybrid BM25 + vector retrieval fused with production RRF — returns top_k source_ids."""
    embed = embed_fn or default_embed_fn
    bm25_ids = _bm25_rank(query, corpus)
    vector_ids = _vector_rank(query, corpus, embed)
    return reciprocal_rank_fusion(bm25_ids, vector_ids)[:top_k]


def recall_at_k(
    corpus: list[dict],
    queries: list[dict],
    k: int = 5,
    embed_fn: EmbedFn | None = None,
) -> float:
    """Fraction of queries whose expected source appears in the top-k results."""
    total = 0
    hits = 0
    for q in queries:
        expected = set(q.get("expected_source_ids") or [])
        if not expected:
            continue
        total += 1
        got = set(retrieve_offline(q["query"], corpus, top_k=k, embed_fn=embed_fn))
        if expected & got:
            hits += 1
    return hits / total if total else 0.0


def groundedness(
    corpus: list[dict],
    queries: list[dict],
    k: int = 5,
    embed_fn: EmbedFn | None = None,
) -> float:
    """Fraction of returned chunks that come from the known corpus (no fabrication).

    The retriever must never surface a source_id that is not in the corpus; a value
    below 1.0 means the retrieval layer fabricated/leaked an unknown source.
    """
    corpus_ids = {c["source_id"] for c in corpus}
    returned = 0
    grounded = 0
    for q in queries:
        for sid in retrieve_offline(q["query"], corpus, top_k=k, embed_fn=embed_fn):
            returned += 1
            if sid in corpus_ids:
                grounded += 1
    return grounded / returned if returned else 1.0
