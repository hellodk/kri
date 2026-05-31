"""Service for the email approval gate on destructive node actions (#291)."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.pending_action import PendingAction

_TTL_MINUTES = 15


async def create_pending_action(
    db: AsyncSession,
    *,
    node_id: uuid.UUID,
    action_type: str,
    params: dict,
    requested_by: str,
) -> PendingAction:
    import secrets as _secrets
    now = datetime.now(UTC)
    action = PendingAction(
        node_id=node_id,
        action_type=action_type,
        params=json.dumps(params),
        requested_by=requested_by,
        approval_token=_secrets.token_urlsafe(32),
        status="pending",
        created_at=now,
        expires_at=now + timedelta(minutes=_TTL_MINUTES),
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return action


async def get_by_token(db: AsyncSession, token: str) -> PendingAction | None:
    result = await db.execute(
        select(PendingAction).where(PendingAction.approval_token == token)
    )
    return result.scalar_one_or_none()


async def approve(db: AsyncSession, action: PendingAction) -> PendingAction:
    now = datetime.now(UTC)
    if action.status != "pending":
        return action
    if action.expires_at < now:
        action.status = "expired"
        await db.commit()
        return action
    action.status = "approved"
    action.executed_at = now
    await db.commit()
    await db.refresh(action)
    return action


async def reject(db: AsyncSession, action: PendingAction) -> PendingAction:
    action.status = "rejected"
    await db.commit()
    await db.refresh(action)
    return action


async def expire_old(db: AsyncSession) -> int:
    """Mark all pending actions past their expiry as expired. Returns count."""
    from sqlalchemy import update
    now = datetime.now(UTC)
    result = await db.execute(
        update(PendingAction)
        .where(PendingAction.status == "pending", PendingAction.expires_at < now)
        .values(status="expired")
    )
    await db.commit()
    return result.rowcount  # type: ignore[attr-defined]


async def _send_approval_email(action: PendingAction, node, requested_by: str) -> None:
    """Send approval email for a destructive action (non-blocking)."""
    import asyncio

    from fleet_platform.services.platform_settings_svc import (
        KRI_API_URL,
        SMTP_HOST,
    )

    def _send():
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from fleet_platform.db.session import get_sync_db
        from fleet_platform.services.platform_settings_svc import (
            DIGEST_RECIPIENTS,
            SMTP_FROM,
            SMTP_PASSWORD,
            SMTP_PORT,
            SMTP_USERNAME,
            decrypt_secret,
            get_setting_sync,
        )

        with get_sync_db() as db:
            smtp_host = get_setting_sync(db, SMTP_HOST)
            if not smtp_host:
                return
            api_url = get_setting_sync(db, KRI_API_URL) or "http://localhost"
            smtp_port = int(get_setting_sync(db, SMTP_PORT) or "587")
            smtp_user = get_setting_sync(db, SMTP_USERNAME)
            raw_pw = get_setting_sync(db, SMTP_PASSWORD)
            smtp_password = decrypt_secret(raw_pw) if raw_pw else ""
            from_addr = get_setting_sync(db, SMTP_FROM) or smtp_user or ""
            recipients_raw = get_setting_sync(db, DIGEST_RECIPIENTS) or ""
            recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

        if not recipients:
            return

        node_name = (
            getattr(node, "hostname", None)
            or getattr(node, "minion_id", None)
            or str(action.node_id)
        )
        approve_url = f"{api_url}/api/v1/actions/{action.approval_token}/approve"
        reject_url = f"{api_url}/api/v1/actions/{action.approval_token}/reject"

        body = f"""
<html><body style="font-family:sans-serif;color:#111827">
  <h2 style="color:#D97706">&#9888; Action Approval Required</h2>
  <p><strong>Requested by:</strong> {requested_by}</p>
  <p><strong>Node:</strong> {node_name}</p>
  <p><strong>Action:</strong> {action.action_type}</p>
  <p><strong>Expires:</strong> 15 minutes from request</p>
  <p style="margin-top:24px">
    <a href="{approve_url}"
       style="background:#16A34A;color:white;padding:10px 20px;border-radius:6px;
              text-decoration:none;margin-right:12px">&#10003; Approve</a>
    <a href="{reject_url}"
       style="background:#DC2626;color:white;padding:10px 20px;border-radius:6px;
              text-decoration:none">&#10007; Reject</a>
  </p>
</body></html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[kri] Approval required: {action.action_type} on {node_name}"
        msg["From"] = from_addr
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body, "html"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port) as s:
                s.ehlo()
                s.starttls()
                if smtp_user and smtp_password:
                    s.login(smtp_user, smtp_password)
                s.sendmail(from_addr, recipients, msg.as_string())
        except Exception:
            pass

    await asyncio.get_event_loop().run_in_executor(None, _send)
