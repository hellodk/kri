# fleet_platform/api/routes/ansible/misc.py
"""Miscellaneous ansible routes: /nodes/{node_id}/collect-grains, /tasks/{task_id}."""

import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.node import Node

from ._router import router


@router.post("/nodes/{node_id}/collect-grains", status_code=202)
async def collect_grains(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Trigger an Ansible run to collect grains from a live node and push to ingest."""
    from sqlalchemy import select as _sel

    result = await db.execute(_sel(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    if not node.bootstrap_ip:
        raise HTTPException(status_code=400, detail="Node has no bootstrap_ip — run bootstrap first")

    from fleet_platform.workers.celery_app import celery_app

    task = celery_app.send_task(
        "fleet_platform.workers.ansible_tasks.collect_node_grains",
        args=[str(node_id)],
        queue="maintenance",
    )
    return {"task_id": task.id, "node_id": str(node_id), "status": "queued"}


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    _: dict = Depends(require_role("viewer", "operator", "admin")),
):
    """Return Celery task state + result for any queued task."""
    from celery.result import AsyncResult

    from fleet_platform.workers.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)
    payload: dict = {"task_id": task_id, "state": result.state}
    if result.ready():
        try:
            payload["result"] = result.result if not isinstance(result.result, Exception) else str(result.result)
        except Exception:
            payload["result"] = None
    return payload
