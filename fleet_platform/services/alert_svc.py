"""Alert evaluation and delivery service."""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.alert import AlertEvent, AlertRule, WebhookConfig
from fleet_platform.models.node import Node
from fleet_platform.models.security import VulnerabilityFinding

if TYPE_CHECKING:
    pass


def _validate_webhook_url(url: str) -> None:
    """Raise ValueError if the webhook URL is unsafe (SSRF protection).

    Blocks:
    - Non-HTTP/HTTPS schemes
    - Private, loopback, and link-local IP ranges (RFC 1918, 127.0.0.0/8, 169.254.0.0/16)
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid webhook URL scheme: {parsed.scheme!r}. Only http/https allowed.")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook URL has no hostname.")
    try:
        resolved_ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        if resolved_ip.is_private or resolved_ip.is_loopback or resolved_ip.is_link_local:
            raise ValueError(
                f"Webhook URL resolves to a private/loopback/link-local address ({resolved_ip}). "
                "Only public internet URLs are allowed."
            )
    except socket.gaierror:
        pass  # DNS resolution failed — let urlopen fail naturally


async def evaluate_alerts(db: AsyncSession) -> None:
    """Run all alert rule checks and fire events as needed."""
    now = datetime.now(UTC)

    # Fetch all enabled rules
    result = await db.execute(
        select(AlertRule).where(AlertRule.enabled == True)  # noqa: E712
    )
    rules = result.scalars().all()

    if not rules:
        return

    for rule in rules:
        if rule.event_type == "node_offline":
            await _check_node_offline(rule, now, db)
        elif rule.event_type == "drift_threshold":
            await _check_drift_threshold(rule, now, db)
        elif rule.event_type == "cve_found":
            await _check_cve_found(rule, now, db)
        elif rule.event_type == "key_pending":
            await _check_key_pending(rule, now, db)

    await db.commit()


async def _check_node_offline(rule: AlertRule, now: datetime, db: AsyncSession) -> None:
    """Fire node_offline for nodes offline for > 10 minutes, once per 30 min."""
    cutoff = now - timedelta(minutes=10)
    result = await db.execute(
        select(Node).where(
            Node.status == "offline",
            Node.last_seen_at < cutoff,
        )
    )
    nodes = result.scalars().all()

    recent_cutoff = now - timedelta(minutes=30)
    for node in nodes:
        # Check if already fired in last 30 min
        existing = await db.execute(
            select(AlertEvent).where(
                AlertEvent.rule_id == rule.id,
                AlertEvent.node_id == node.id,
                AlertEvent.fired_at > recent_cutoff,
            )
        )
        if existing.scalar_one_or_none():
            continue

        msg = f"Node '{node.hostname or node.minion_id}' has been offline since {node.last_seen_at}"
        event = AlertEvent(
            rule_id=rule.id,
            node_id=node.id,
            message=msg,
            fired_at=now,
            delivered=False,
        )
        db.add(event)
        await db.flush()
        await _deliver_alert(rule, event, db)


async def _check_drift_threshold(rule: AlertRule, now: datetime, db: AsyncSession) -> None:
    """Fire drift_threshold for nodes exceeding drift score."""
    if rule.threshold is None:
        return

    result = await db.execute(
        select(Node).where(Node.drift_score > rule.threshold)
    )
    nodes = result.scalars().all()

    recent_cutoff = now - timedelta(minutes=30)
    for node in nodes:
        existing = await db.execute(
            select(AlertEvent).where(
                AlertEvent.rule_id == rule.id,
                AlertEvent.node_id == node.id,
                AlertEvent.fired_at > recent_cutoff,
            )
        )
        if existing.scalar_one_or_none():
            continue

        msg = (
            f"Node '{node.hostname or node.minion_id}' drift score {node.drift_score} "
            f"exceeds threshold {rule.threshold}"
        )
        event = AlertEvent(
            rule_id=rule.id,
            node_id=node.id,
            message=msg,
            fired_at=now,
            delivered=False,
        )
        db.add(event)
        await db.flush()
        await _deliver_alert(rule, event, db)


async def _check_cve_found(rule: AlertRule, now: datetime, db: AsyncSession) -> None:
    """Fire cve_found for CRITICAL/HIGH findings added in the last hour."""
    one_hour_ago = now - timedelta(hours=1)
    # threshold: 1=CRITICAL, 2=HIGH (and above)
    threshold = rule.threshold or 1
    if threshold <= 1:
        severities = ["CRITICAL"]
    else:
        severities = ["CRITICAL", "HIGH"]

    result = await db.execute(
        select(VulnerabilityFinding).where(
            VulnerabilityFinding.severity.in_(severities),
            VulnerabilityFinding.scanned_at > one_hour_ago,
        )
    )
    findings = result.scalars().all()

    recent_cutoff = now - timedelta(minutes=30)
    # Group by node_id to avoid spam
    seen_nodes: set = set()
    for finding in findings:
        node_id = finding.node_id
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)

        existing = await db.execute(
            select(AlertEvent).where(
                AlertEvent.rule_id == rule.id,
                AlertEvent.node_id == node_id,
                AlertEvent.fired_at > recent_cutoff,
            )
        )
        if existing.scalar_one_or_none():
            continue

        msg = (
            f"New {finding.severity} CVE '{finding.cve_id}' found on node "
            f"(id={node_id}) affecting package '{finding.package_name}'"
        )
        event = AlertEvent(
            rule_id=rule.id,
            node_id=node_id,
            message=msg,
            fired_at=now,
            delivered=False,
        )
        db.add(event)
        await db.flush()
        await _deliver_alert(rule, event, db)


async def _check_key_pending(rule: AlertRule, now: datetime, db: AsyncSession) -> None:
    """Fire key_pending if minions_pre PKI dir has pending keys, once per hour."""
    import os

    pki_dir = "/etc/salt/pki/master/minions_pre"
    try:
        pending_keys = os.listdir(pki_dir)
        pending_count = len([k for k in pending_keys if not k.startswith(".")])
    except (OSError, PermissionError):
        return

    if pending_count == 0:
        return

    one_hour_ago = now - timedelta(hours=1)
    existing = await db.execute(
        select(AlertEvent).where(
            AlertEvent.rule_id == rule.id,
            AlertEvent.node_id == None,  # noqa: E711
            AlertEvent.fired_at > one_hour_ago,
        )
    )
    if existing.scalar_one_or_none():
        return

    msg = f"{pending_count} Salt minion key(s) pending approval in {pki_dir}"
    event = AlertEvent(
        rule_id=rule.id,
        node_id=None,
        message=msg,
        fired_at=now,
        delivered=False,
    )
    db.add(event)
    await db.flush()
    await _deliver_alert(rule, event, db)


async def _deliver_alert(rule: AlertRule, alert_event: AlertEvent, db: AsyncSession) -> None:
    """Send alert to all enabled webhook targets."""
    result = await db.execute(
        select(WebhookConfig).where(WebhookConfig.enabled == True)  # noqa: E712
    )
    webhooks = result.scalars().all()

    if not webhooks:
        return

    node_id_str = str(alert_event.node_id) if alert_event.node_id else None
    fired_at_iso = alert_event.fired_at.isoformat() if alert_event.fired_at else None

    delivered_any = False
    for webhook in webhooks:
        try:
            _validate_webhook_url(webhook.url)
            if webhook.type == "slack":
                payload = {"text": f"\U0001f6a8 *kri alert*: {alert_event.message}"}
            else:
                payload = {
                    "event": rule.event_type,
                    "message": alert_event.message,
                    "node_id": node_id_str,
                    "fired_at": fired_at_iso,
                }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook.url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            delivered_any = True
        except Exception:
            pass

    if delivered_any:
        alert_event.delivered = True
