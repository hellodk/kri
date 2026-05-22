# fleet_platform/api/routes/ingest.py
import asyncio
import ipaddress as _ipaddress
import os
import tempfile
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.models.execution import ExecutionJob, ExecutionResult
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.node import Node, Tag
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


def _is_valid_ip(addr: str) -> bool:
    try:
        _ipaddress.ip_address(addr)
        return True
    except ValueError:
        return False


def _extract_storage_gb(grains: dict) -> float | None:
    for key in ("disk_total", "disks_total_size"):
        val = grains.get(key)
        if val is not None:
            try:
                return round(float(val) / 1024, 1)  # MB → GB
            except (TypeError, ValueError):
                pass
    disk_info = grains.get("disk_info", [])
    if isinstance(disk_info, list) and disk_info:
        try:
            total_bytes = sum(d.get("size", 0) for d in disk_info if isinstance(d, dict))
            if total_bytes:
                return round(total_bytes / (1024 ** 3), 1)
        except (TypeError, ValueError):
            pass
    return None


def _extract_node_updates(grains: dict) -> dict:
    ip: str | None = None
    _skip_prefixes = ("127.", "169.254.", "::1", "fe80")

    ip4 = grains.get("ip4_interfaces", {})
    for iface, addrs in ip4.items():
        if iface in ("lo", "lo0"):
            continue
        for addr in addrs:
            if not _is_valid_ip(addr):
                continue
            if not any(addr.startswith(p) for p in _skip_prefixes):
                ip = addr
                break
        if ip:
            break

    if ip is None:
        fqdn_ips = grains.get("fqdn_ip4", [])
        ip = next(
            (a for a in fqdn_ips
             if _is_valid_ip(a) and not any(a.startswith(p) for p in _skip_prefixes)),
            None,
        )

    # Hostname resolution priority:
    # 1. `host` grain — the actual short machine name (uname -n), always reliable
    # 2. `fqdn` grain — only if it is NOT a reverse-DNS artefact (.ip6.arpa /
    #    .in-addr.arpa) which Salt/Ansible produces when PTR lookup returns the
    #    Tailscale IPv6 record instead of the real name
    # 3. `id` grain — the minion ID, always present as a last resort
    raw_host = grains.get("host") or ""
    raw_fqdn = grains.get("fqdn") or ""
    fqdn_valid = raw_fqdn and not raw_fqdn.lower().endswith((".ip6.arpa", ".in-addr.arpa"))

    hostname = raw_host or (raw_fqdn if fqdn_valid else None) or grains.get("id")

    return {
        "hostname": hostname,
        "ip_address": ip,
        "os_version": grains.get("osrelease"),
        "os_build": grains.get("osbuild"),
        "hardware_model": grains.get("productname"),
        "cpu_cores": grains.get("num_cpus"),
        "ram_gb": grains.get("mem_total", 0) / 1024 if grains.get("mem_total") else None,
        "storage_gb": _extract_storage_gb(grains),
        "status": "online",
    }


_SYSTEM_TAG_GRAINS: list[tuple[str, str]] = [
    # (tag_key, grain_key)
    ("hostname",        "fqdn"),
    ("ip",              None),          # computed from ip4_interfaces — set below
    ("arch",            "cpuarch"),
    ("model",           "productname"),
    ("macos_version",   "osrelease"),
    ("serial",          "serialnumber"),
    ("os",              "osfullname"),
    ("kernel",          "kernelrelease"),
    ("cpu",             "cpu_model"),
]


async def _upsert_system_tags(db: AsyncSession, node: Node, grains: dict, now: datetime) -> None:
    """Write auto-populated tags from Salt grains. Existing user tags with same key are skipped."""
    tag_values: dict[str, str] = {}

    for tag_key, grain_key in _SYSTEM_TAG_GRAINS:
        if grain_key is None:
            continue
        val = grains.get(grain_key)
        if val and str(val).strip():
            tag_values[tag_key] = str(val).strip()

    # IP: use the already-computed ip_address on the node (extracted by _extract_node_updates)
    if node.ip_address:
        tag_values["ip"] = str(node.ip_address)

    if not tag_values:
        return

    # Batch fetch existing tags for this node
    existing_result = await db.execute(
        select(Tag).where(Tag.node_id == node.id, Tag.key.in_(list(tag_values)))
    )
    existing_tags = {t.key: t for t in existing_result.scalars()}

    for key, value in tag_values.items():
        if key in existing_tags:
            tag = existing_tags[key]
            # Update system tags freely; skip user tags entirely
            if tag.source == "system":
                tag.value = value
            # user tags with same key: do not overwrite
        else:
            db.add(Tag(node_id=node.id, key=key, value=value,
                       source="system", created_at=now))


@router.post("/grains")
@limiter.limit("60/minute")
async def ingest_grains(
    request: Request,
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
        # Never overwrite an existing ip_address with None — grains may not carry
        # a valid IP (e.g. Ansible gather_subset:min omits network facts).
        # Keep bootstrap_ip as the authoritative fallback.
        if key == "ip_address" and value is None:
            continue
        setattr(node, key, value)

    # Seed ip_address from bootstrap_ip if it has never been set
    if not node.ip_address and node.bootstrap_ip:
        node.ip_address = node.bootstrap_ip

    db.add(NodeFact(
        node_id=node.id,
        collected_at=now,
        grains=payload.grains,
    ))

    await _upsert_system_tags(db, node, payload.grains, now)

    # Update iOS-specific tracking fields from grains (before commit)
    from fleet_platform.services.ios_tracking_svc import update_node_from_grains
    await update_node_from_grains(node.id, payload.grains, db)

    await db.commit()
    compute_drift.delay(str(node.id))

    # Auto-trigger SBOM indexing when grains contain package data
    grains = payload.grains
    has_packages = bool(
        grains.get("pkgs") or grains.get("brew_pkgs") or grains.get("pip_pkgs")
    )
    if has_packages:
        from fleet_platform.workers.sbom_tasks import index_sbom_from_grains
        index_sbom_from_grains.delay(str(node.id))

    return {"status": "ok", "node_id": str(node.id)}


@router.post("/executions")
@limiter.limit("120/minute")
async def ingest_executions(
    request: Request,
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
@limiter.limit("10/minute")
async def ingest_sbom(
    request: Request,
    minion_id: str,
    x_node_token: str | None = Header(alias="X-Node-Token", default=None),
    db: AsyncSession = Depends(get_db),
):
    if not x_node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Node-Token")

    node = await _resolve_node(minion_id, x_node_token, db)

    _MAX_SBOM_BYTES = 50 * 1024 * 1024  # 50 MB
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_SBOM_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="SBOM upload exceeds maximum size of 50MB",
        )

    size = 0
    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".json",
        prefix=f"sbom_{node.id}_",
        mode="wb",
    )
    try:
        async for chunk in request.stream():
            size += len(chunk)
            if size > _MAX_SBOM_BYTES:
                tmp.close()
                os.unlink(tmp.name)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="SBOM upload exceeds maximum size of 50MB",
                )
            tmp.write(chunk)
        tmp.close()
    except HTTPException:
        raise
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
