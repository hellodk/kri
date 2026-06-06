# fleet_platform/api/routes/search.py
"""Unified fuzzy search across nodes, groups, playbooks, executions, and LLM queries.

Uses PostgreSQL pg_trgm for fuzzy matching — handles typos, partial IDs, and
substring matches. Results are grouped by entity type and ranked by similarity score.
UUID prefix search allows finding any execution by its first 8 characters.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user

router = APIRouter(prefix="/api/v1")

_TRGM_THRESHOLD = 0.15  # minimum similarity score (0–1). Lower = fuzzier.
_MAX_PER_TYPE = 5  # results per entity type
_UUID_PREFIX_LEN = 8  # search by first N chars of a UUID


def _is_uuid_prefix(q: str) -> bool:
    """True only if q looks like a UUID prefix — requires 8+ hex chars or contains a hyphen."""
    cleaned = q.replace("-", "")
    has_hyphen = "-" in q
    return all(c in "0123456789abcdefABCDEF" for c in cleaned) and (has_hyphen or len(cleaned) >= _UUID_PREFIX_LEN)


def _uuid_like(q: str) -> str:
    """Build a LIKE pattern for UUID prefix search."""
    return f"{q.lower()}%"


async def _search_nodes(db: AsyncSession, q: str, pattern: str) -> list[dict]:
    rows = await db.execute(
        text("""
            SELECT id, hostname, minion_id, ip_address, status,
                   greatest(
                       similarity(coalesce(hostname,''), :q),
                       similarity(minion_id, :q),
                       similarity(coalesce(ip_address::text,''), :q)
                   ) AS score
            FROM nodes
            WHERE coalesce(hostname,'') ILIKE :pat
               OR minion_id ILIKE :pat
               OR coalesce(ip_address::text,'') ILIKE :pat
               OR coalesce(hostname,'') % :q
               OR minion_id % :q
            ORDER BY score DESC
            LIMIT :lim
        """),
        {"q": q, "pat": pattern, "lim": _MAX_PER_TYPE},
    )
    return [
        {
            "type": "node",
            "id": str(r.id),
            "title": r.hostname or r.minion_id,
            "subtitle": f"{r.ip_address or 'no IP'} · {r.status}",
            "status": r.status,
            "url": f"/nodes/{r.id}",
            "score": float(r.score),
            # top-level for backwards compat — real values not display strings
            "minion_id": r.minion_id,
            "ip_address": r.ip_address,
            "hostname": r.hostname or r.minion_id,
        }
        for r in rows.all()
    ]


async def _search_groups(db: AsyncSession, q: str, pattern: str) -> list[dict]:
    rows = await db.execute(
        text("""
            SELECT g.id, g.name, g.type, count(gm.node_id) AS member_count,
                   similarity(g.name, :q) AS score
            FROM groups g
            LEFT JOIN group_members gm ON gm.group_id = g.id
            WHERE g.name ILIKE :pat OR g.name % :q
            GROUP BY g.id, g.name, g.type
            ORDER BY score DESC
            LIMIT :lim
        """),
        {"q": q, "pat": pattern, "lim": _MAX_PER_TYPE},
    )
    return [
        {
            "type": "group",
            "id": str(r.id),
            "title": r.name,
            "subtitle": f"{r.member_count} node{'s' if r.member_count != 1 else ''} · {r.type}",
            "url": f"/groups/{r.id}",
            "score": float(r.score),
        }
        for r in rows.all()
    ]


async def _search_ansible_jobs(db: AsyncSession, q: str, pattern: str, is_uuid: bool) -> list[dict]:
    if is_uuid:
        uuid_pat = _uuid_like(q)
        rows = await db.execute(
            text("""
                SELECT id, playbook, target_label, status, created_at, 1.0 AS score
                FROM ansible_jobs
                WHERE cast(id AS text) LIKE :uuid_pat
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"uuid_pat": uuid_pat, "lim": _MAX_PER_TYPE},
        )
    else:
        rows = await db.execute(
            text("""
                SELECT id, playbook, target_label, status, created_at,
                       greatest(
                           similarity(playbook, :q),
                           similarity(target_label, :q)
                       ) AS score
                FROM ansible_jobs
                WHERE playbook ILIKE :pat
                   OR target_label ILIKE :pat
                   OR playbook % :q
                   OR target_label % :q
                ORDER BY score DESC, created_at DESC
                LIMIT :lim
            """),
            {"q": q, "pat": pattern, "lim": _MAX_PER_TYPE},
        )
    return [
        {
            "type": "ansible_job",
            "id": str(r.id),
            "title": r.playbook,
            "subtitle": f"on {r.target_label} · {r.status} · {str(r.id)[:8]}",
            "status": r.status,
            "url": f"/playbook-job/{r.id}",
            "score": float(r.score),
        }
        for r in rows.all()
    ]


async def _search_salt_executions(db: AsyncSession, q: str, pattern: str, is_uuid: bool) -> list[dict]:
    if is_uuid:
        uuid_pat = _uuid_like(q)
        rows = await db.execute(
            text("""
                SELECT id, type, status, started_at, 1.0 AS score
                FROM execution_jobs
                WHERE cast(id AS text) LIKE :uuid_pat
                   OR (salt_jid IS NOT NULL AND salt_jid LIKE :uuid_pat)
                ORDER BY started_at DESC NULLS LAST
                LIMIT :lim
            """),
            {"uuid_pat": uuid_pat, "lim": _MAX_PER_TYPE},
        )
    else:
        rows = await db.execute(
            text("""
                SELECT id, type, status, started_at,
                       similarity(type, :q) AS score
                FROM execution_jobs
                WHERE type ILIKE :pat OR salt_jid ILIKE :pat
                ORDER BY score DESC, started_at DESC NULLS LAST
                LIMIT :lim
            """),
            {"q": q, "pat": pattern, "lim": _MAX_PER_TYPE},
        )
    return [
        {
            "type": "salt_execution",
            "id": str(r.id),
            "title": r.type or "Salt execution",
            "subtitle": f"{r.status} · {str(r.id)[:8]}",
            "status": r.status,
            "url": f"/executions/{r.id}",
            "score": float(r.score),
        }
        for r in rows.all()
    ]


async def _search_llm_queries(db: AsyncSession, q: str, pattern: str, is_uuid: bool, user_id: str) -> list[dict]:
    # Only search last 30 days of LLM queries to keep results relevant
    cutoff = datetime.now(UTC) - timedelta(days=30)
    if is_uuid:
        uuid_pat = _uuid_like(q)
        rows = await db.execute(
            text("""
                SELECT id, intent, prompt, created_at, 1.0 AS score
                FROM llm_query_log
                WHERE cast(id AS text) LIKE :uuid_pat
                  AND created_at > :cutoff
                  AND user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"uuid_pat": uuid_pat, "cutoff": cutoff, "lim": _MAX_PER_TYPE, "user_id": user_id},
        )
    else:
        rows = await db.execute(
            text("""
                SELECT id, intent, prompt, created_at,
                       similarity(prompt, :q) AS score
                FROM llm_query_log
                WHERE prompt % :q
                  AND created_at > :cutoff
                  AND user_id = :user_id
                ORDER BY score DESC, created_at DESC
                LIMIT :lim
            """),
            {"q": q, "cutoff": cutoff, "lim": _MAX_PER_TYPE, "user_id": user_id},
        )
    return [
        {
            "type": "llm_query",
            "id": str(r.id),
            "title": f"AI Query — {r.intent}",
            "subtitle": f"{r.prompt[:60]}{'…' if len(r.prompt) > 60 else ''} · {str(r.id)[:8]}",
            "url": "/overview",  # LLM queries go to overview/history
            "score": float(r.score),
        }
        for r in rows.all()
    ]


@router.get("/search")
async def search(
    q: str = Query(min_length=2, description="Search term — min 2 chars, UUID prefix supported"),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user),
):
    """Unified fuzzy search across nodes, groups, playbook jobs, Salt executions, and LLM queries.

    Supports:
    - Partial name/hostname matches with typo tolerance (pg_trgm)
    - UUID prefix search (first 8+ hex chars of any execution ID)
    - IP address substring matching for nodes
    """
    q = q.strip()
    if len(q) < 2:
        return {
            "query": "",
            "is_uuid_search": False,
            "results": [],
            "items": [],
            "nodes": [],
            "total": 0,
            "page": 1,
            "per_page": 0,
        }
    pattern = f"%{q}%"
    is_uuid = _is_uuid_prefix(q)

    # Run all searches in parallel using asyncio.gather would require separate sessions.
    # For simplicity and connection pool safety, run sequentially — each query is indexed.
    results: list[dict] = []

    nodes = await _search_nodes(db, q, pattern)
    groups = await _search_groups(db, q, pattern)
    ansible = await _search_ansible_jobs(db, q, pattern, is_uuid)
    salt = await _search_salt_executions(db, q, pattern, is_uuid)
    llm = await _search_llm_queries(db, q, pattern, is_uuid, user_id=claims["sub"])

    results = nodes + groups + ansible + salt + llm

    # Sort by score descending, then recency (score already encodes this within each type)
    results.sort(key=lambda r: r["score"], reverse=True)

    return {
        "query": q,
        "is_uuid_search": is_uuid,
        "results": results,
        # Backwards-compat fields for existing frontend
        "items": [
            {
                **r,
                "hostname": r.get("hostname", r.get("title")),
                "minion_id": r.get("minion_id", ""),  # now real minion_id
                "ip_address": r.get("ip_address"),
            }
            for r in nodes
        ],
        "nodes": nodes,
        "total": len(results),
        "page": 1,
        "per_page": _MAX_PER_TYPE * 5,
    }
