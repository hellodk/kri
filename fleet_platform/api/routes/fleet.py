# fleet_platform/api/routes/fleet.py
import asyncio
import json
import re
import secrets
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db, get_redis
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, hash_password, require_role
from fleet_platform.models.node import Node
from fleet_platform.schemas.fleet import FleetOverviewResponse
from fleet_platform.schemas.node_import import (
    ImportCommitRequest,
    ImportCommitResponse,
    ImportRow,
    ImportValidateRequest,
    ImportValidateResponse,
)
from fleet_platform.services.node_import import (
    dedup_rows,
    parse_csv,
    parse_paste,
    validate_row,
)
from fleet_platform.services.ssh_credential_link import upsert_owner_ssh_credential

router = APIRouter(prefix="/api/v1/fleet")

_OVERVIEW_CACHE_KEY = "fleet:overview"
_OVERVIEW_TTL = 15  # seconds

# Only letters, digits, dots, hyphens and underscores are valid in a minion ID.
_MINION_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


@router.get("/nodes/check-minion-id")
async def check_minion_id(
    id: str = Query(..., description="Minion ID to check for availability"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> dict:
    """
    Check whether a minion_id is available (not already in use).
    Returns the existing node summary if taken, so the UI can link to it.
    """
    if not _MINION_ID_RE.match(id):
        raise HTTPException(
            status_code=422,
            detail="Invalid minion_id format. Only [a-zA-Z0-9._-] allowed.",
        )
    result = await db.execute(select(Node).where(Node.minion_id == id))
    existing = result.scalar_one_or_none()
    if existing:
        return {
            "available": False,
            "existing_node": {
                "id": str(existing.id),
                "hostname": existing.hostname,
                "status": existing.status,
                "bootstrap_status": existing.bootstrap_status,
            },
        }
    return {"available": True, "existing_node": None}


@router.get("/overview", response_model=FleetOverviewResponse)
async def fleet_overview(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    _: dict = Depends(get_current_user),
):
    cached = await redis.get(_OVERVIEW_CACHE_KEY)
    if cached:
        return FleetOverviewResponse(**json.loads(cached))

    rows = await db.execute(
        select(
            func.count().label("total"),
            func.sum(case((Node.status == "online", 1), else_=0)).label("online"),
            func.sum(case((Node.status == "stale", 1), else_=0)).label("stale"),
            func.sum(case((Node.status == "offline", 1), else_=0)).label("offline"),
            func.sum(case((Node.status == "unknown", 1), else_=0)).label("unknown"),
            func.coalesce(func.avg(Node.drift_score), 0).label("avg_drift"),
            func.sum(case((Node.drift_score <= 5, 1), else_=0)).label("clean"),
            func.sum(case(((Node.drift_score >= 6) & (Node.drift_score <= 20), 1), else_=0)).label("low"),
            func.sum(case(((Node.drift_score >= 21) & (Node.drift_score <= 50), 1), else_=0)).label("medium"),
            func.sum(case(((Node.drift_score >= 51) & (Node.drift_score <= 80), 1), else_=0)).label("high"),
            func.sum(case((Node.drift_score >= 81, 1), else_=0)).label("critical"),
        )
    )
    row = rows.one()
    now = datetime.now(UTC)

    data = FleetOverviewResponse(
        total_nodes=row.total or 0,
        online=row.online or 0,
        stale=row.stale or 0,
        offline=row.offline or 0,
        unknown=row.unknown or 0,
        avg_drift_score=int(row.avg_drift or 0),
        nodes_clean=row.clean or 0,
        nodes_low=row.low or 0,
        nodes_medium=row.medium or 0,
        nodes_high=row.high or 0,
        nodes_critical=row.critical or 0,
        last_updated=now,
    )

    await redis.setex(_OVERVIEW_CACHE_KEY, _OVERVIEW_TTL, data.model_dump_json())
    return data


# ─── Bulk node import ──────────────────────────────────────────────────────────


async def _import_from_salt(db: AsyncSession) -> list[dict]:
    """Pull accepted minions from the Salt master, if available."""
    try:
        from fleet_platform.services.salt_client import list_accepted_minions  # type: ignore[import]

        minions = await list_accepted_minions()
        return [{"minion_id": m, "hostname": m, "ip": ""} for m in minions]
    except Exception:
        return []


@router.post("/nodes/import/validate", response_model=ImportValidateResponse)
async def import_validate(
    payload: ImportValidateRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
) -> ImportValidateResponse:
    """Dry-run: parse and classify rows from the given source without writing to the DB."""
    if payload.source == "paste":
        raw_rows = parse_paste(payload.text or "")
    elif payload.source == "csv":
        raw_rows = parse_csv(payload.csv_content or "", payload.mapping)
    elif payload.source == "salt":
        raw_rows = await _import_from_salt(db)
    else:
        raise HTTPException(status_code=400, detail="unknown source")

    res = await db.execute(select(Node.minion_id, Node.ip_address))
    existing_minions: set[str] = set()
    existing_ips: set[str] = set()
    for mid, ip in res.all():
        existing_minions.add(mid)
        if ip:
            existing_ips.add(str(ip))

    validated = dedup_rows([validate_row(r, existing_minions, existing_ips) for r in raw_rows])
    summary: dict = {"new": 0, "duplicate": 0, "invalid": 0, "total": len(validated)}
    for r in validated:
        status_key = r["status"]
        summary[status_key] = summary.get(status_key, 0) + 1

    return ImportValidateResponse(
        rows=[ImportRow(**r) for r in validated],
        summary=summary,
    )


@router.post("/nodes/import/commit", response_model=ImportCommitResponse)
async def import_commit(
    payload: ImportCommitRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
) -> ImportCommitResponse:
    """Commit validated rows to the database, skipping duplicates and invalid rows."""
    new_rows = [r for r in payload.rows if r.status == "new"]
    skipped = len(payload.rows) - len(new_rows)
    created_ids: list[str] = []

    for r in new_rows:
        token_hash = await asyncio.to_thread(hash_password, secrets.token_urlsafe(32))
        node = Node(
            minion_id=r.minion_id,
            hostname=r.hostname or r.minion_id,
            ip_address=r.ip or None,
            node_token_hash=token_hash,
            first_seen_at=datetime.now(UTC),
            status="unknown",
        )
        db.add(node)
        await db.flush()
        created_ids.append(str(node.id))

        # SSH username (#725): persist into the node's dedicated Credential row
        # + FK instead of the deprecated inline ssh_username column.
        _ssh_user = payload.ssh_username or r.ssh_user or None
        if _ssh_user:
            _cred_id = await upsert_owner_ssh_credential(
                db,
                owner_name=f"node:{node.minion_id}",
                current_credential_id=None,
                ssh_username=_ssh_user,
            )
            if _cred_id is not None:
                node.credential_id = _cred_id

        if payload.group_id:
            from fleet_platform.models.group import GroupMember

            db.add(
                GroupMember(
                    group_id=uuid.UUID(payload.group_id),
                    node_id=node.id,
                    added_at=datetime.now(UTC),
                )
            )

    await audit(
        db,
        actor=claims["email"],
        action="node.bulk_import",
        resource_type="node",
        resource_id=None,
        new_value={"created": len(created_ids), "skipped": skipped},
    )
    await db.commit()

    bootstrap_queued = 0
    if payload.auto_bootstrap:
        try:
            from fleet_platform.workers.ansible_tasks import bootstrap_node

            for nid in created_ids:
                bootstrap_node.delay(nid)
                bootstrap_queued += 1
        except Exception:
            pass

    return ImportCommitResponse(
        created=len(created_ids),
        skipped=skipped,
        node_ids=created_ids,
        bootstrap_queued=bootstrap_queued,
    )
