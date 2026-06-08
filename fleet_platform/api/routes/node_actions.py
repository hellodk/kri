"""HTTP endpoints for destructive node action approval gate (#291)."""

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.models.node import Node
from fleet_platform.models.pending_action import PendingAction
from fleet_platform.services import pending_action_svc

router = APIRouter(prefix="/api/v1/nodes", tags=["node-actions"])
actions_router = APIRouter(prefix="/api/v1/actions", tags=["node-actions"])

# Safe charset for process/service names and launchd labels (mirrors salt_ops.py minion-id pattern)
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_PID_RE = re.compile(r"^\d+$")


def _validate_action_params(action_type: str, params: dict) -> None:
    """Validate params by action_type and enforce the protected-target denylist.

    Raises HTTPException 422 for malformed inputs, 403 for protected targets.
    """
    if action_type.startswith("process_"):
        pid = str(params.get("pid", ""))
        if not _PID_RE.match(pid):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid pid {pid!r}; digits only.",
            )
        name = params.get("name") or params.get("process_name")
        if name is not None:
            if not _NAME_RE.match(str(name)):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid process name {name!r}.",
                )
            if PendingAction.is_protected_target(str(name)):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"{name!r} is a protected process and cannot be controlled remotely.",
                )
    elif action_type.startswith("service_"):
        svc = str(params.get("service", ""))
        if not _NAME_RE.match(svc):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid service name {svc!r}.",
            )
        if PendingAction.is_protected_target(svc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{svc!r} is a protected service and cannot be controlled remotely.",
            )


class NodeActionRequest(BaseModel):
    action_type: str
    params: dict = {}


class PendingActionResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    action_type: str
    status: str
    expires_at: datetime
    message: str

    model_config = {"from_attributes": True}


@router.post("/{node_id}/actions", response_model=PendingActionResponse, status_code=202)
async def request_node_action(
    node_id: uuid.UUID,
    payload: NodeActionRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Request a node action. Destructive actions are gated behind email approval."""
    if PendingAction.is_forbidden(payload.action_type):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Action '{payload.action_type}' is not permitted. "
                "Remote force-kill is disabled for safety. Use the service manager or SSH."
            ),
        )

    _validate_action_params(payload.action_type, payload.params)

    node_result = await db.execute(select(Node).where(Node.id == node_id))
    node = node_result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    if not PendingAction.is_destructive(payload.action_type):
        # Non-destructive: execute immediately (placeholder — actual Salt call TBD)
        await audit(
            db,
            actor=claims["sub"],
            action=payload.action_type,
            resource_type="node",
            resource_id=node_id,
            new_value=payload.params,
        )
        return PendingActionResponse(
            id=uuid.uuid4(),
            node_id=node_id,
            action_type=payload.action_type,
            status="executed",
            expires_at=datetime.now(UTC),
            message=f"Action '{payload.action_type}' queued for execution.",
        )

    action = await pending_action_svc.create_pending_action(
        db,
        node_id=node_id,
        action_type=payload.action_type,
        params=payload.params,
        requested_by=claims["sub"],
    )

    # Send approval email (non-blocking — failure must not block the response)
    try:
        await pending_action_svc._send_approval_email(action, node, claims["sub"])
    except Exception:
        pass  # email failure must not block

    await audit(
        db,
        actor=claims["sub"],
        action=f"{payload.action_type}_requested",
        resource_type="node",
        resource_id=node_id,
        new_value={"action_id": str(action.id), "params": payload.params},
    )

    return PendingActionResponse(
        id=action.id,
        node_id=action.node_id,
        action_type=action.action_type,
        status=action.status,
        expires_at=action.expires_at,
        message="Approval email sent. Action will expire in 15 minutes.",
    )


@router.get("/{node_id}/processes")
async def list_processes(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _claims: dict = Depends(require_role("operator", "admin")),
):
    """List running processes on a node via Salt ps.list_processes."""
    from sqlalchemy import select as _sel

    node_result = await db.execute(_sel(Node).where(Node.id == node_id))
    node = node_result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    from fleet_platform.workers.salt_tasks import run_salt_cmd

    task = run_salt_cmd.delay(
        function="ps.list_processes",
        target_minions=[node.minion_id],
        args=[],
    )
    return {"task_id": task.id, "minion_id": node.minion_id}


@router.get("/{node_id}/services")
async def list_services(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _claims: dict = Depends(require_role("operator", "admin")),
):
    """List services on a node via Salt service.get_all + service.status."""
    from sqlalchemy import select as _sel

    node_result = await db.execute(_sel(Node).where(Node.id == node_id))
    node = node_result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    from fleet_platform.workers.salt_tasks import run_salt_cmd

    task = run_salt_cmd.delay(
        function="service.get_all",
        target_minions=[node.minion_id],
        args=[],
    )
    return {"task_id": task.id, "minion_id": node.minion_id}


@router.post("/{node_id}/ask-ai")
async def ask_ai_about_node(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Ask the LLM for recommendations about a specific node."""
    from datetime import timedelta

    from sqlalchemy import desc
    from sqlalchemy import func as sqlfunc
    from sqlalchemy import select as _sel

    from fleet_platform.models.alert import AlertEvent as _AlertEvent
    from fleet_platform.models.drift import DriftRecord as _DriftRecord
    from fleet_platform.models.node import Node as _Node
    from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot as _Snapshot
    from fleet_platform.services.llm_caller import LLMCallError, call_anthropic, call_openai_compat
    from fleet_platform.services.llm_context import build_fleet_context
    from fleet_platform.services.llm_svc import get_decrypted_api_key, get_default_endpoint

    node_result = await db.execute(_sel(_Node).where(_Node.id == node_id))
    node = node_result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    endpoint = await get_default_endpoint(db)
    if not endpoint or not endpoint.enabled:
        raise HTTPException(status_code=422, detail="No LLM endpoint configured.")

    # Build node-specific context
    node_name = node.hostname or node.minion_id
    cpu_info = f"{node.cpu_usage_pct:.1f}%" if node.cpu_usage_pct is not None else "unknown"
    mem_info = f"{node.mem_usage_pct:.1f}%" if node.mem_usage_pct is not None else "unknown"
    drift_info = str(node.drift_score)

    # Fetch latest health snapshot for richer metrics
    snapshot_result = await db.execute(
        _sel(_Snapshot).where(_Snapshot.node_id == node_id).order_by(desc(_Snapshot.collected_at)).limit(1)
    )
    snapshot = snapshot_result.scalar_one_or_none()

    # Fetch latest drift record for detail on what drifted
    drift_result = await db.execute(
        _sel(_DriftRecord).where(_DriftRecord.node_id == node_id).order_by(desc(_DriftRecord.computed_at)).limit(1)
    )
    latest_drift = drift_result.scalar_one_or_none()

    # Count recent alert events (last 24 h)
    since = datetime.now(UTC) - timedelta(hours=24)
    alert_count_result = await db.execute(
        _sel(sqlfunc.count(_AlertEvent.id)).where(_AlertEvent.node_id == node_id).where(_AlertEvent.fired_at >= since)
    )
    recent_alert_count: int = alert_count_result.scalar_one() or 0

    # Compose enriched context block
    lines: list[str] = [
        f"Analyze node '{node_name}' and provide actionable recommendations.\n",
        f"Node status: {node.status}",
        f"CPU usage: {cpu_info}",
        f"Memory usage: {mem_info}",
        f"Drift score: {drift_info}/100",
        f"Alert events (last 24 h): {recent_alert_count}",
    ]

    if snapshot:
        if snapshot.disk_root_pct is not None:
            lines.append(f"Disk usage (/): {snapshot.disk_root_pct}%")
        if snapshot.disk_root_used_gb is not None and snapshot.disk_root_total_gb is not None:
            lines.append(
                f"Disk space: {float(snapshot.disk_root_used_gb):.1f} GB used"
                f" / {float(snapshot.disk_root_total_gb):.1f} GB total"
            )
        if snapshot.cpu_load_1m is not None:
            lines.append(
                f"CPU load avg: {float(snapshot.cpu_load_1m):.2f} (1m)"
                + (f" / {float(snapshot.cpu_load_5m):.2f} (5m)" if snapshot.cpu_load_5m is not None else "")
                + (f" / {float(snapshot.cpu_load_15m):.2f} (15m)" if snapshot.cpu_load_15m is not None else "")
            )
        if snapshot.uptime_seconds is not None:
            uptime_h = snapshot.uptime_seconds // 3600
            lines.append(f"Uptime: {uptime_h} hours")
        if snapshot.thermal_pressure:
            lines.append(f"Thermal pressure: {snapshot.thermal_pressure}")

    if latest_drift:
        if latest_drift.missing_packages:
            pkgs = ", ".join(str(p) for p in latest_drift.missing_packages[:5])
            lines.append(f"Missing packages (up to 5): {pkgs}")
        if latest_drift.extra_packages:
            pkgs = ", ".join(str(p) for p in latest_drift.extra_packages[:5])
            lines.append(f"Extra packages (up to 5): {pkgs}")
        if latest_drift.service_drift:
            svcs = ", ".join(str(s) for s in latest_drift.service_drift[:3])
            lines.append(f"Service drift (up to 3): {svcs}")
        if latest_drift.version_mismatches:
            mismatches = len(latest_drift.version_mismatches)
            lines.append(f"Package version mismatches: {mismatches}")

    lines.append(
        "\nProvide: (1) Assessment of current health, "
        "(2) Top 2-3 actionable recommendations, "
        "(3) Risk level (Low/Medium/High). "
        "Be concise. Do not invent data not shown above."
    )

    node_context = "\n".join(lines)

    system_prompt = await build_fleet_context(db, "fleet_query")
    api_key = get_decrypted_api_key(endpoint)
    model_caps = (
        [c.strip() for c in endpoint.model_capabilities.split(",") if c.strip()] if endpoint.model_capabilities else []
    )

    try:
        if endpoint.provider == "anthropic":
            content, input_tokens, output_tokens = await call_anthropic(
                api_key=api_key or "",
                model=endpoint.model,
                max_tokens=min(endpoint.max_tokens, 512),
                system_prompt=system_prompt,
                user_prompt=node_context,
            )
        else:
            content, input_tokens, output_tokens = await call_openai_compat(
                base_url=endpoint.base_url,
                api_key=api_key,
                model=endpoint.model,
                max_tokens=min(endpoint.max_tokens, 512),
                system_prompt=system_prompt,
                user_prompt=node_context,
                model_context_length=endpoint.model_context_length,
                model_capabilities=model_caps,
            )
    except LLMCallError as exc:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc

    return {
        "node_id": str(node_id),
        "node_name": node_name,
        "recommendation": content,
        "model_used": endpoint.model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


@router.get("/{node_id}/metrics")
async def get_node_metrics(
    node_id: uuid.UUID,
    range: str = "1h",
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Proxy Prometheus range queries for a specific node's metrics.

    Returns time-series data for CPU, memory, disk, network.
    Falls back gracefully when Prometheus is unavailable or node_exporter not running.
    """
    import httpx as _httpx
    from sqlalchemy import select as _sel

    from fleet_platform.models.node import Node
    from fleet_platform.services.platform_settings_svc import PROMETHEUS_URL, get_setting

    node_result = await db.execute(_sel(Node).where(Node.id == node_id))
    node = node_result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # ip_address is the current live address (from grains); bootstrap_ip is the provisioning address.
    # node_exporter binds to ip_address so use it first — bootstrap_ip is only a fallback.
    node_ip = node.ip_address or node.bootstrap_ip
    if not node_ip:
        return {"available": False, "reason": "Node has no IP address — bootstrap first"}

    prom_base = await get_setting(db, PROMETHEUS_URL) or "http://prometheus-operated.monitoring.svc:9090"
    instance = f"{node_ip}:9100"

    # Time range
    range_map = {"15m": "15m", "1h": "1h", "6h": "6h", "24h": "24h"}
    prom_range = range_map.get(range, "1h")
    step_map = {"15m": "30s", "1h": "60s", "6h": "5m", "24h": "20m"}
    step = step_map.get(range, "60s")

    queries = {
        "cpu": f'100 - avg(rate(node_cpu_seconds_total{{instance="{instance}",mode="idle"}}[5m])) * 100',
        "mem_used_pct": (
            f'(1 - node_memory_MemAvailable_bytes{{instance="{instance}"}}'
            f' / node_memory_MemTotal_bytes{{instance="{instance}"}}) * 100'
        ),
        "disk_read_kbs": f'rate(node_disk_read_bytes_total{{instance="{instance}"}}[5m]) / 1024',
        "disk_write_kbs": f'rate(node_disk_written_bytes_total{{instance="{instance}"}}[5m]) / 1024',
        "net_rx_kbs": f'rate(node_network_receive_bytes_total{{instance="{instance}",device!="lo"}}[5m]) / 1024',
        "net_tx_kbs": f'rate(node_network_transmit_bytes_total{{instance="{instance}",device!="lo"}}[5m]) / 1024',
    }

    results: dict = {"available": True, "instance": instance, "range": range, "series": {}}

    try:
        async with _httpx.AsyncClient(timeout=8.0) as client:
            for key, query in queries.items():
                try:
                    resp = await client.get(
                        f"{prom_base}/api/v1/query_range",
                        params={"query": query, "start": f"now-{prom_range}", "end": "now", "step": step},
                    )
                    data = resp.json()
                    if data.get("status") == "success":
                        result_data = data.get("data", {}).get("result", [])
                        if result_data:
                            values = result_data[0].get("values", [])
                            results["series"][key] = [
                                {"t": int(v[0]), "v": float(v[1])} for v in values if v[1] != "NaN"
                            ]
                        else:
                            results["series"][key] = []
                    else:
                        results["series"][key] = []
                except Exception:
                    results["series"][key] = []
    except Exception as exc:
        return {"available": False, "reason": f"Cannot reach Prometheus: {exc}"}

    # Check if we got any data at all
    total_points = sum(len(v) for v in results["series"].values())
    if total_points == 0:
        results["available"] = False
        results["reason"] = f"No metrics for {instance} — is node_exporter running? Deploy it via the Overview tab."

    return results


@actions_router.get("/{token}/approve")
async def approve_action(token: str, db: AsyncSession = Depends(get_db)):
    """Approve a pending destructive action via the emailed approval link.

    Security: no session auth required — the token (secrets.token_urlsafe(32),
    ~192 bits entropy, one-time use, 15-minute TTL) IS the credential, matching
    the password-reset link pattern. The token is delivered only to configured
    SMTP recipients and is never reusable after approval/rejection/expiry.
    """
    action = await pending_action_svc.get_by_token(db, token)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action = await pending_action_svc.approve(db, action)
    if action.status == "expired":
        return {"status": "expired", "message": "This approval link has expired."}
    if action.status == "approved":
        # TODO: dispatch actual Salt execution
        return {"status": "approved", "message": f"Action '{action.action_type}' approved and queued."}
    return {"status": action.status}


@actions_router.get("/{token}/reject")
async def reject_action(token: str, db: AsyncSession = Depends(get_db)):
    """Reject a pending destructive action via the emailed rejection link."""
    action = await pending_action_svc.get_by_token(db, token)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action = await pending_action_svc.reject(db, action)
    return {"status": "rejected", "message": "Action rejected."}
