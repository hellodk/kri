# fleet_platform/api/routes/ingest.py
import asyncio
import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.models.execution import ExecutionJob, ExecutionResult
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.node import Node
from fleet_platform.schemas.ingest import ExecutionIngestPayload, GrainIngestPayload
from fleet_platform.services.node_status import verify_node_token
from fleet_platform.workers.drift_tasks import compute_drift
from fleet_platform.workers.sbom_tasks import index_sbom

router = APIRouter(prefix="/api/v1/ingest")


async def _resolve_node(minion_id: str, token: str, db: AsyncSession) -> Node:
    """Look up node by minion_id and verify token. Raises 404 or 401."""
    result = await db.execute(select(Node).where(Node.minion_id == minion_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    valid = await asyncio.to_thread(verify_node_token, token, node.node_token_hash)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid node token")
    return node


def _extract_node_updates(grains: dict) -> dict:
    """Map Salt grain keys to Node column values."""
    # Skip loopback and link-local; prefer en0/en1 style interfaces
    ip = None
    _skip_prefixes = ("127.", "169.254.", "::1", "fe80")
    ip4 = grains.get("ip4_interfaces", {})
    for iface, addrs in ip4.items():
        if iface in ("lo", "lo0"):
            continue
        for addr in addrs:
            if not any(addr.startswith(p) for p in _skip_prefixes):
                ip = addr
                break
        if ip:
            break

    # Fallback: use Salt's pre-filtered fqdn_ip4 list
    if not ip:
        fqdn_ips = grains.get("fqdn_ip4", [])
        ip = next(
            (a for a in fqdn_ips if not any(a.startswith(p) for p in _skip_prefixes)),
            None,
        )

    mem_mb = grains.get("mem_total")
    ram_gb = Decimal(str(round(mem_mb / 1024, 2))) if mem_mb else None

    return {
        "hostname": grains.get("id") or grains.get("host"),
        "ip_address": ip,
        "os_version": grains.get("osrelease"),
        "os_build": grains.get("osbuild"),
        "hardware_model": grains.get("productname"),
        "cpu_cores": grains.get("num_cpus"),
        "ram_gb": ram_gb,
        "status": "online",
    }


@router.post("/grains")
async def ingest_grains(
    payload: GrainIngestPayload,
    x_node_token: str | None = Header(alias="X-Node-Token", default=None),
    db: AsyncSession = Depends(get_db),
):
    if not x_node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Node-Token")

    node = await _resolve_node(payload.minion_id, x_node_token, db)
    now = datetime.now(UTC)

    updates = _extract_node_updates(payload.grains)
    updates["last_seen_at"] = now
    for key, value in updates.items():
        setattr(node, key, value)

    db.add(NodeFact(
        node_id=node.id,
        collected_at=now,
        grains=payload.grains,
    ))

    await db.commit()
    compute_drift.delay(str(node.id))

    return {"status": "ok", "node_id": str(node.id)}


@router.post("/executions")
async def ingest_executions(
    payload: ExecutionIngestPayload,
    x_node_token: str | None = Header(alias="X-Node-Token", default=None),
    db: AsyncSession = Depends(get_db),
):
    if not x_node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Node-Token")

    node = await _resolve_node(payload.minion_id, x_node_token, db)
    now = datetime.now(UTC)

    # Check for existing job with same JID (idempotency)
    if payload.jid:
        existing = await db.execute(
            select(ExecutionJob).where(
                ExecutionJob.salt_jid == payload.jid,
                ExecutionJob.target_id == node.id,
            )
        )
        if existing_job := existing.scalar_one_or_none():
            return {"status": "ok", "job_id": str(existing_job.id)}

    job = ExecutionJob(
        salt_jid=payload.jid,
        type=payload.fun,
        target_type="node",
        target_id=node.id,
        triggered_by="salt",
        status="completed",
        started_at=now,
        completed_at=now,
        metadata_={},
    )
    db.add(job)
    await db.flush()

    result = ExecutionResult(
        job_id=job.id,
        node_id=node.id,
        status="success" if payload.success and payload.retcode == 0 else "failure",
        exit_code=payload.retcode,
        changes=payload.return_data,
        completed_at=now,
    )
    db.add(result)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Race condition — another request already inserted this JID; return existing
        existing = await db.execute(
            select(ExecutionJob).where(
                ExecutionJob.salt_jid == payload.jid,
                ExecutionJob.target_id == node.id,
            )
        )
        existing_job = existing.scalar_one()
        return {"status": "ok", "job_id": str(existing_job.id)}

    return {"status": "ok", "job_id": str(job.id)}


@router.post("/sbom/{minion_id}", status_code=status.HTTP_202_ACCEPTED)
async def ingest_sbom(
    minion_id: str,
    request: Request,
    x_node_token: str | None = Header(alias="X-Node-Token", default=None),
    db: AsyncSession = Depends(get_db),
):
    if not x_node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Node-Token")

    node = await _resolve_node(minion_id, x_node_token, db)

    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".json",
        prefix=f"sbom_{node.id}_",
    )
    try:
        async for chunk in request.stream():
            tmp.write(chunk)
        tmp.close()
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise

    try:
        index_sbom.delay(node_id=str(node.id), file_path=tmp.name)
    except Exception:
        os.unlink(tmp.name)
        raise

    return {"status": "queued", "node_id": str(node.id)}
