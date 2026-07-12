"""HTTP endpoints for destructive node action approval gate (#291)."""

import json
import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.api.limiter import limiter
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.metrics import node_action_total
from fleet_platform.models.node import Node
from fleet_platform.models.pending_action import PendingAction
from fleet_platform.services import pending_action_svc

logger = logging.getLogger(__name__)

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
    elif action_type in ("harden", "unharden"):
        # Node-wide harden/unharden takes no target params — it applies a fixed
        # Salt state whose never-disable denylist (salt-minion, sshd, exo, …) is
        # baked into base.harden_compute itself. Nothing to validate per-target.
        return


def _build_salt_invocation(action_type: str, params: dict) -> tuple[str, list[str]]:
    """Map an approved action to (salt_function, args).

    Raises HTTPException(400) if the action_type is unsupported or unmappable.
    Nodes are macOS (Darwin): SIGTERM=15, SIGSTOP=17, SIGCONT=19.
    """
    if action_type.startswith("process_"):
        pid = str(params.get("pid", ""))
        sig = {"process_stop": "15", "process_suspend": "17", "process_resume": "19"}.get(action_type)
        if not sig:
            raise HTTPException(status_code=400, detail=f"Unsupported process action {action_type!r}")
        return "ps.kill_pid", [pid, f"signal={sig}"]
    if action_type.startswith("service_"):
        svc = str(params.get("service", ""))
        fn = {
            "service_stop": "service.stop",
            "service_disable": "service.disable",
            "service_start": "service.start",
            "service_restart": "service.restart",
            "service_enable": "service.enable",
        }.get(action_type)
        if not fn:
            raise HTTPException(status_code=400, detail=f"Unsupported service action {action_type!r}")
        return fn, [svc]
    if action_type in ("harden", "unharden"):
        # Reversible compute-harden: apply the conservative disable set, or its
        # exact inverse. The state's never-disable list is the safety boundary.
        state = "base.harden_compute" if action_type == "harden" else "base.unharden_compute"
        return "state.apply", [state]
    raise HTTPException(status_code=400, detail=f"Unsupported action {action_type!r}")


class NodeActionRequest(BaseModel):
    action_type: str
    params: dict = {}
    dry_run: bool = False


class PendingActionResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID | None
    action_type: str
    status: str
    expires_at: datetime
    message: str

    model_config = {"from_attributes": True}


@router.post("/{node_id}/actions", response_model=PendingActionResponse, status_code=202)
@limiter.limit("5/minute")
async def request_node_action(
    request: Request,
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

    if payload.dry_run:
        would = "require email approval" if PendingAction.is_destructive(payload.action_type) else "execute immediately"
        return PendingActionResponse(
            id=uuid.uuid4(),
            node_id=node_id,
            action_type=payload.action_type,
            status="dry_run",
            expires_at=datetime.now(UTC),
            message=f"Dry run: '{payload.action_type}' is valid and would {would}. No action created, no email sent.",
        )

    if not PendingAction.is_destructive(payload.action_type):
        # Non-destructive (start/restart/enable/resume): execute immediately, no approval.
        function, args = _build_salt_invocation(payload.action_type, payload.params)
        from fleet_platform.workers.celery_app import celery_app

        celery_app.send_task(
            "fleet_platform.workers.salt_tasks.run_salt_cmd",
            kwargs={"function": function, "target_minions": [node.minion_id], "args": args},
            queue="maintenance",
        )
        node_action_total.labels(action_type=payload.action_type, status="requested").inc()
        node_action_total.labels(action_type=payload.action_type, status="executed").inc()
        await audit(
            db,
            actor=claims["sub"],
            action=f"{payload.action_type}_executed",
            resource_type="node",
            resource_id=node_id,
            new_value={"function": function, "args": args, "params": payload.params},
        )
        return PendingActionResponse(
            id=uuid.uuid4(),
            node_id=node_id,
            action_type=payload.action_type,
            status="executed",
            expires_at=datetime.now(UTC),
            message=f"Action '{payload.action_type}' dispatched.",
        )

    action = await pending_action_svc.create_pending_action(
        db,
        node_id=node_id,
        action_type=payload.action_type,
        params=payload.params,
        requested_by=claims["sub"],
    )
    node_action_total.labels(action_type=payload.action_type, status="requested").inc()

    # Send approval email (non-blocking — failure must not block the response)
    try:
        await pending_action_svc._send_approval_email(action, node, claims["sub"])
    except Exception as exc:
        logger.warning(
            "approval email send failed for action=%s: %s",
            action.id,
            exc,
            exc_info=True,
        )  # email failure must not block

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
    from fleet_platform.workers.celery_app import celery_app

    task = celery_app.send_task(
        "fleet_platform.workers.salt_tasks.run_salt_cmd",
        kwargs={"function": "service.get_all", "target_minions": [node.minion_id], "args": []},
        queue="maintenance",
    )
    return {"task_id": task.id, "minion_id": node.minion_id}


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
        results["reason"] = (
            f"No metrics for {instance} — is node_exporter running? "
            "Monitoring installs during bootstrap; re-run bootstrap for this node if it is missing."
        )

    return results


def _confirm_html(action: PendingAction | None, token: str) -> str:
    """Build the side-effect-free confirmation page for an emailed approval link.

    All dynamic values are HTML-escaped. When the action is still actionable the
    page renders Approve/Reject buttons that POST (never GET) to the mutating
    endpoints; otherwise it shows the settled status.
    """
    import html as _html

    style = (
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "max-width:520px;margin:48px auto;padding:0 20px;color:#111827"
    )
    if action is None:
        return (
            f'<html><body style="{style}"><h2>Action not found</h2>'
            "<p>This approval link is invalid or has already been cleaned up.</p></body></html>"
        )

    now = datetime.now(UTC)
    expires_at = action.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    actionable = action.status == "pending" and expires_at is not None and expires_at >= now

    safe_type = _html.escape(str(action.action_type))
    safe_status = _html.escape(str(action.status))
    safe_node = _html.escape(str(action.node_id))
    safe_by = _html.escape(str(action.requested_by or "unknown"))
    safe_token = _html.escape(token)

    if actionable:
        decision = f"""
  <form method="post" action="/api/v1/actions/{safe_token}/approve" style="display:inline">
    <button type="submit" style="background:#16A34A;color:#fff;border:0;padding:10px 22px;
      border-radius:6px;font-size:14px;cursor:pointer;margin-right:12px">&#10003; Approve</button>
  </form>
  <form method="post" action="/api/v1/actions/{safe_token}/reject" style="display:inline">
    <button type="submit" style="background:#DC2626;color:#fff;border:0;padding:10px 22px;
      border-radius:6px;font-size:14px;cursor:pointer">&#10007; Reject</button>
  </form>"""
    elif action.status == "pending":
        decision = "<p style='color:#B45309'>This approval link has expired.</p>"
    else:
        decision = f"<p style='color:#6B7280'>Already <strong>{safe_status}</strong> — no further action possible.</p>"

    return f"""<html><body style="{style}">
  <h2 style="color:#D97706">&#9888; Confirm node action</h2>
  <table style="font-size:14px;line-height:1.8">
    <tr><td style="color:#6B7280;padding-right:16px">Action</td><td><strong>{safe_type}</strong></td></tr>
    <tr><td style="color:#6B7280;padding-right:16px">Node</td><td>{safe_node}</td></tr>
    <tr><td style="color:#6B7280;padding-right:16px">Requested by</td><td>{safe_by}</td></tr>
    <tr><td style="color:#6B7280;padding-right:16px">Status</td><td>{safe_status}</td></tr>
  </table>
  <div style="margin-top:24px">{decision}</div>
</body></html>"""


@actions_router.get("/{token}")
async def action_confirm_page(token: str, db: AsyncSession = Depends(get_db)):
    """Render the GET confirmation page for an emailed approval link (#644).

    This endpoint is intentionally side-effect-free so mail-client/link-unfurler
    prefetch cannot decide an action. The page POSTs to ``/approve`` or
    ``/reject`` only when the operator clicks a button.
    """
    action = await pending_action_svc.get_by_token(db, token)
    if not action:
        return HTMLResponse(_confirm_html(None, token), status_code=404)
    return HTMLResponse(_confirm_html(action, token))


@actions_router.post("/{token}/approve")
@limiter.limit("20/minute")
async def approve_action(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    """Approve a pending destructive action (POST-only, #644).

    Security: no session auth required — the token (secrets.token_urlsafe(32),
    ~192 bits entropy, one-time use, 15-minute TTL) IS the credential, matching
    the password-reset link pattern. The token is delivered only to configured
    SMTP recipients and is never reusable after approval/rejection/expiry. Mutation
    requires POST so prefetch of the emailed (GET) link cannot trigger it; the
    approval itself is an atomic compare-and-swap so concurrent POSTs can't
    double-dispatch (TOCTOU).
    """
    action = await pending_action_svc.get_by_token(db, token)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action, claimed = await pending_action_svc.approve(db, action)
    if not claimed:
        # Expired, or another approver/rejecter already settled it — never re-dispatch.
        if action.status == "expired":
            return {"status": "expired", "message": "This approval link has expired."}
        return {"status": action.status, "message": f"Action already {action.status}."}
    # claimed == True: this caller owns the single pending -> approved transition.
    params = json.loads(action.params or "{}")
    # Defense-in-depth: re-enforce denylist at execution time (#615 guards at request time)
    target = params.get("name") or params.get("process_name") or params.get("service")
    if target and PendingAction.is_protected_target(str(target)):
        action.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=403,
            detail=f"{target!r} is a protected target; execution refused.",
        )
    node = (await db.execute(select(Node).where(Node.id == action.node_id))).scalar_one_or_none()
    if not node:
        action.status = "failed"
        await db.commit()
        raise HTTPException(status_code=404, detail="Node not found")
    function, args = _build_salt_invocation(action.action_type, params)
    from fleet_platform.workers.salt_tasks import finalize_node_action, run_salt_cmd

    run_salt_cmd.apply_async(
        kwargs={"function": function, "target_minions": [node.minion_id], "args": args},
        link=finalize_node_action.s(str(action.id)),
    )
    node_action_total.labels(action_type=action.action_type, status="approved").inc()
    action.status = "executing"  # finalize_node_action sets executed/failed on completion
    await db.commit()
    await audit(
        db,
        actor="approval-link",
        action=f"{action.action_type}_dispatched",
        resource_type="node",
        resource_id=action.node_id,
        new_value={"action_id": str(action.id), "function": function, "args": args},
    )
    return {
        "status": "executing",
        "message": f"Action '{action.action_type}' approved and dispatched; awaiting result.",
    }


@actions_router.post("/{token}/reject")
@limiter.limit("20/minute")
async def reject_action(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    """Reject a pending destructive action (POST-only, #644).

    Mutation requires POST so prefetch of the emailed (GET) link cannot trigger
    it; the rejection is an atomic compare-and-swap so audit/metrics fire once.
    """
    action = await pending_action_svc.get_by_token(db, token)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action, claimed = await pending_action_svc.reject(db, action)
    if claimed:
        node_action_total.labels(action_type=action.action_type, status="rejected").inc()
        await audit(
            db,
            actor="approval-link",
            action=f"{action.action_type}_rejected",
            resource_type="node",
            resource_id=action.node_id,
            new_value={"action_id": str(action.id)},
        )
    return {"status": "rejected", "message": "Action rejected."}
