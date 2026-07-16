# fleet_platform/api/routes/fleet.py
import asyncio
import json
import logging
import re
import secrets
import types
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db, get_redis
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, hash_password, require_role
from fleet_platform.core.validators import MINION_ID_RE
from fleet_platform.models.group import Group
from fleet_platform.models.node import Node
from fleet_platform.schemas.fleet import FleetOverviewResponse
from fleet_platform.schemas.node_import import (
    ImportCommitRequest,
    ImportCommitResponse,
    ImportRow,
    ImportValidateRequest,
    ImportValidateResponse,
)
from fleet_platform.services.node_health import (
    HEALTH_DEGRADED,
    HEALTH_DOWN,
    HEALTH_MAINTENANCE,
    HEALTH_ONLINE,
    HEALTH_UNKNOWN,
    compute_health,
)
from fleet_platform.services.node_import import (
    dedup_rows,
    parse_csv,
    parse_paste,
    validate_row,
)
from fleet_platform.services.ssh_probe import SSH_OK, SSH_UNKNOWN, probe_node_ssh

router = APIRouter(prefix="/api/v1/fleet")
logger = logging.getLogger(__name__)

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

    # Health rollup counts: pull the per-node signals and fold them through the
    # same `compute_health` used by the per-node HealthBadge, so the summary tiles
    # and the cards/table agree on one read (single source of truth). The overview
    # is cached for _OVERVIEW_TTL, so this extra lightweight scan is amortised.
    health_rows = await db.execute(select(Node.status, Node.ssh_state, Node.maintenance_mode))
    health_counts = {
        HEALTH_ONLINE: 0,
        HEALTH_DEGRADED: 0,
        HEALTH_DOWN: 0,
        HEALTH_UNKNOWN: 0,
        HEALTH_MAINTENANCE: 0,
    }
    for status, ssh_state, maintenance_mode in health_rows.all():
        health = compute_health(status, ssh_state, bool(maintenance_mode))
        health_counts[health] = health_counts.get(health, 0) + 1

    data = FleetOverviewResponse(
        total_nodes=row.total or 0,
        online=row.online or 0,
        stale=row.stale or 0,
        offline=row.offline or 0,
        unknown=row.unknown or 0,
        health_online=health_counts[HEALTH_ONLINE],
        health_degraded=health_counts[HEALTH_DEGRADED],
        health_down=health_counts[HEALTH_DOWN],
        health_unknown=health_counts[HEALTH_UNKNOWN],
        health_maintenance=health_counts[HEALTH_MAINTENANCE],
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


async def _get_or_create_default_group(db: AsyncSession) -> Group:
    """Return the seeded 'default' group, creating it if migration 065's seed is
    absent.

    Guarantees every group-less imported node still joins a group (upholding the
    node-in-≥1-group invariant) and resolves a credential via credential_groups,
    instead of being silently skipped when the seed is missing (#994/C4). Never
    returns None.
    """
    grp = (await db.execute(select(Group).where(Group.name == "default"))).scalar_one_or_none()
    if grp is None:
        grp = Group(name="default", type="static")
        db.add(grp)
        await db.flush()
    return grp


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

    # SSH reachability probe (#1012): warn-only signal so the operator can see
    # which rows are bootstrap-able before committing. Never blocks commit.
    creds = {
        "ssh_user": payload.ssh_username,
        "ssh_password": payload.ssh_password,
        "ssh_key": payload.ssh_key,
        "auth_mode": payload.ssh_auth_mode or ("key" if payload.ssh_key and not payload.ssh_password else "password"),
    }
    sem = asyncio.Semaphore(10)

    async def _probe_row(row: dict) -> None:
        ip = row.get("ip")
        if not ip:
            row["ssh_state"] = SSH_UNKNOWN
            row["ssh_detail"] = "no IP"
            return
        stub = types.SimpleNamespace(ip_address=ip, minion_id=row.get("minion_id"))
        async with sem:
            result = await asyncio.to_thread(probe_node_ssh, stub, creds, timeout=3)
        row["ssh_state"] = result["state"]
        row["ssh_detail"] = result["detail"]
        if not row.get("reason") and result["state"] != SSH_OK:
            row["reason"] = result["detail"]

    await asyncio.gather(*(_probe_row(r) for r in validated))

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
    """Commit validated rows to the database, skipping duplicates and invalid rows.

    When ``auto_bootstrap`` is set, each newly created node is queued for bootstrap
    through the same path as the dedicated bootstrap endpoint (group enforcement,
    audit, and Celery dispatch with the node's target IP). Credentials resolve
    from the node's group (credential_groups) — no longer persisted per-node.
    """
    # Bootstrap requires group membership; a single import applies one group to all
    # rows, so demand the group up front rather than failing per-node in the worker.
    if payload.auto_bootstrap and not payload.group_id:
        raise HTTPException(
            status_code=400,
            detail="Select a group to bootstrap imported nodes — bootstrapping "
            "requires the node to belong to a group with SSH credentials.",
        )

    # Secrets stay bound to locals — never sent to the broker (#495). These are
    # only forwarded to queue_node_bootstrap below (auto_bootstrap); they are no
    # longer persisted as a per-node Credential (#986 — credentials are
    # group-scoped via credential_groups).
    _ssh_pw = payload.ssh_password or None
    _ssh_key = payload.ssh_key or None

    # Commit only acts on rows the validate step marked "new". Re-check the
    # minion_id format defensively here too: a client could POST status="new"
    # with a malformed minion_id directly, bypassing the validate endpoint.
    # Such rows are skipped (never persisted) rather than 422-ing the whole batch.
    new_rows = [r for r in payload.rows if r.status == "new" and MINION_ID_RE.match(r.minion_id or "")]
    skipped = len(payload.rows) - len(new_rows)
    created_ids: list[str] = []
    created_nodes: list[Node] = []

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
        created_nodes.append(node)

        # Credentials now reach a node via its group's credential_groups
        # association (#986 Phase 2c) — per-node Credential rows are no longer
        # created here. payload.ssh_username/password/key remain accepted on the
        # request (UI removal is Phase 3) but are intentionally not persisted as
        # a per-node credential.
        if payload.group_id:
            from fleet_platform.models.group import GroupMember

            db.add(
                GroupMember(
                    group_id=uuid.UUID(payload.group_id),
                    node_id=node.id,
                    added_at=datetime.now(UTC),
                )
            )
        else:
            # No explicit group: join the seeded (or freshly created) "default"
            # group so the node always belongs to ≥1 group and resolves a
            # credential via credential_groups — never leave it group-less (#994/C4).
            from fleet_platform.models.group import GroupMember

            _default_group = await _get_or_create_default_group(db)
            db.add(
                GroupMember(
                    group_id=_default_group.id,
                    node_id=node.id,
                    added_at=datetime.now(UTC),
                )
            )

    # Import-supplied SSH creds become the TARGET GROUP's credential (new model,
    # #988): create/update a Credential from the inline creds and map it to the
    # group via credential_groups, so every imported node in that group resolves
    # it. This restores the "type creds during import" workflow inside the
    # group-scoped model (Phase 3 will replace the raw fields with a picker).
    if payload.ssh_username or _ssh_pw or _ssh_key:
        from fleet_platform.services.credential_group_svc import (
            get_group_credential_id,
            set_group_credential,
        )
        from fleet_platform.services.ssh_credential_link import upsert_owner_ssh_credential

        if payload.group_id:
            _grp = await db.get(Group, uuid.UUID(payload.group_id))
        else:
            _grp = await _get_or_create_default_group(db)

        if _grp is not None:
            _prior_credential_id = await get_group_credential_id(db, _grp.id)
            _cred_id = await upsert_owner_ssh_credential(
                db,
                owner_name=f"group:{_grp.name}",
                current_credential_id=_prior_credential_id,
                ssh_username=payload.ssh_username,
                ssh_password=_ssh_pw,
                ssh_key=_ssh_key,
                ssh_auth_mode=payload.ssh_auth_mode or ("key" if (_ssh_key and not _ssh_pw) else "password"),
            )
            if _cred_id is not None:
                # S5 (#1004): the group ALREADY had a shared credential — this
                # upsert rotates it for every EXISTING member, not just the
                # nodes created by this import batch. Surface that loudly via
                # a log warning (the additive response field this would
                # otherwise use lives in ImportCommitResponse, which is out of
                # scope for this fix's touched-file set).
                if _prior_credential_id is not None:
                    from fleet_platform.models.group import GroupMember

                    _created_node_ids = {n.id for n in created_nodes}
                    _existing_count_stmt = (
                        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == _grp.id)
                    )
                    if _created_node_ids:
                        _existing_count_stmt = _existing_count_stmt.where(GroupMember.node_id.notin_(_created_node_ids))
                    _existing_member_count = (await db.execute(_existing_count_stmt)).scalar_one()
                    if _existing_member_count > 0:
                        logger.warning(
                            "import_commit rotated shared SSH credential for group %s (%s): "
                            "%d existing node(s) already in this group will use the new "
                            "credential on next resolution",
                            _grp.name,
                            _grp.id,
                            _existing_member_count,
                        )
                await set_group_credential(db, _grp.id, _cred_id)

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
        from fleet_platform.services.bootstrap_svc import (
            BootstrapGroupRequired,
            queue_node_bootstrap,
        )

        for node in created_nodes:
            # Can't SSH-bootstrap a node with no address — skip silently and let the
            # operator supply an IP/hostname later via a targeted bootstrap.
            target_ip = node.ip_address
            if not target_ip:
                continue
            try:
                await queue_node_bootstrap(
                    db,
                    node,
                    target_ip=target_ip,
                    actor=claims["email"],
                    ssh_username=payload.ssh_username or None,
                    ssh_password=_ssh_pw,
                    ssh_key=_ssh_key,
                )
                bootstrap_queued += 1
            except BootstrapGroupRequired:
                # group_id was enforced above, so this is unexpected; skip the node
                # rather than aborting the whole (already-committed) import.
                continue

    return ImportCommitResponse(
        created=len(created_ids),
        skipped=skipped,
        node_ids=created_ids,
        bootstrap_queued=bootstrap_queued,
    )
