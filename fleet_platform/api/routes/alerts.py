"""Alert rules, webhook configs, and alert events API."""

from __future__ import annotations

import json
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.alert import AlertEvent, AlertRule, WebhookConfig
from fleet_platform.services.alert_svc import _validate_webhook_url

router = APIRouter(prefix="/api/v1/alerts")


# ── Schemas ───────────────────────────────────────────────────────────


class CreateRuleBody(BaseModel):
    name: str
    event_type: str
    threshold: int | None = None
    enabled: bool = True


class CreateWebhookBody(BaseModel):
    name: str
    url: str
    type: str = "slack"
    enabled: bool = True


# ── Alert Rules ───────────────────────────────────────────────────────


@router.get("/rules")
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(AlertRule).order_by(AlertRule.created_at))
    rules = result.scalars().all()
    return {
        "items": [
            {
                "id": str(r.id),
                "name": r.name,
                "event_type": r.event_type,
                "threshold": r.threshold,
                "enabled": r.enabled,
                "created_at": r.created_at,
            }
            for r in rules
        ]
    }


@router.post("/rules", status_code=201)
async def create_rule(
    body: CreateRuleBody,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    valid_types = {"node_offline", "drift_threshold", "cve_found", "key_pending"}
    if body.event_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"event_type must be one of: {sorted(valid_types)}",
        )
    rule = AlertRule(
        name=body.name,
        event_type=body.event_type,
        threshold=body.threshold,
        enabled=body.enabled,
        created_at=datetime.now(UTC),
    )
    db.add(rule)
    await db.commit()
    return {
        "id": str(rule.id),
        "name": rule.name,
        "event_type": rule.event_type,
        "threshold": rule.threshold,
        "enabled": rule.enabled,
        "created_at": rule.created_at,
    }


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    await db.delete(rule)
    await db.commit()


# ── Webhook Configs ───────────────────────────────────────────────────


@router.get("/webhooks")
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(WebhookConfig).order_by(WebhookConfig.created_at))
    webhooks = result.scalars().all()
    return {
        "items": [
            {
                "id": str(w.id),
                "name": w.name,
                "url": w.url,
                "type": w.type,
                "enabled": w.enabled,
                "created_at": w.created_at,
            }
            for w in webhooks
        ]
    }


@router.post("/webhooks", status_code=201)
async def create_webhook(
    body: CreateWebhookBody,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    if body.type not in ("slack", "generic"):
        raise HTTPException(status_code=422, detail="type must be 'slack' or 'generic'")
    try:
        _validate_webhook_url(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    webhook = WebhookConfig(
        name=body.name,
        url=body.url,
        type=body.type,
        enabled=body.enabled,
        created_at=datetime.now(UTC),
    )
    db.add(webhook)
    await db.commit()
    return {
        "id": str(webhook.id),
        "name": webhook.name,
        "url": webhook.url,
        "type": webhook.type,
        "enabled": webhook.enabled,
        "created_at": webhook.created_at,
    }


@router.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    result = await db.execute(select(WebhookConfig).where(WebhookConfig.id == webhook_id))
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await db.delete(webhook)
    await db.commit()


# ── Alert Events ──────────────────────────────────────────────────────


@router.get("/events")
async def list_events(
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(AlertEvent).order_by(AlertEvent.fired_at.desc()).limit(limit))
    events = result.scalars().all()
    return {
        "items": [
            {
                "id": str(e.id),
                "rule_id": str(e.rule_id) if e.rule_id else None,
                "node_id": str(e.node_id) if e.node_id else None,
                "message": e.message,
                "fired_at": e.fired_at,
                "delivered": e.delivered,
            }
            for e in events
        ]
    }


# ── Test Webhook ──────────────────────────────────────────────────────


@router.post("/test-webhook/{webhook_id}")
async def test_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    result = await db.execute(select(WebhookConfig).where(WebhookConfig.id == webhook_id))
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    try:
        _validate_webhook_url(webhook.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if webhook.type == "slack":
        payload: dict[str, Any] = {"text": "\U0001f6a8 *kri alert*: This is a test alert from kri fleet platform"}
    else:
        payload = {
            "event": "test",
            "message": "This is a test alert from kri fleet platform",
            "node_id": None,
            "fired_at": datetime.now(UTC).isoformat(),
        }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook.url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)  # nosec B310
        return {"status": "ok", "message": "Test payload delivered successfully"}
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to deliver test payload: {exc}",
        )
