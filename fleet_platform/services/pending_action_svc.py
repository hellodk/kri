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
    result = await db.execute(select(PendingAction).where(PendingAction.approval_token == token))
    return result.scalar_one_or_none()


async def approve(db: AsyncSession, action: PendingAction) -> tuple[PendingAction, bool]:
    """Atomically claim a pending action for approval (TOCTOU-safe, #644).

    Returns ``(action, claimed)``. ``claimed`` is True only for the single caller
    that won the compare-and-swap ``pending`` -> ``approved``; concurrent callers
    get ``False`` and must NOT dispatch (prevents double execution). A still-pending
    action past its expiry is settled to ``expired`` and returned with
    ``claimed=False``.
    """
    from sqlalchemy import update

    now = datetime.now(UTC)
    result = await db.execute(
        update(PendingAction)
        .where(
            PendingAction.id == action.id,
            PendingAction.status == "pending",
            PendingAction.expires_at >= now,
        )
        .values(status="approved", executed_at=now)
    )
    await db.commit()
    if result.rowcount == 1:  # type: ignore[attr-defined]
        await db.refresh(action)
        return action, True
    # Lost the race or past expiry — settle the terminal state for the response.
    await db.execute(
        update(PendingAction)
        .where(
            PendingAction.id == action.id,
            PendingAction.status == "pending",
            PendingAction.expires_at < now,
        )
        .values(status="expired")
    )
    await db.commit()
    await db.refresh(action)
    return action, False


async def reject(db: AsyncSession, action: PendingAction) -> tuple[PendingAction, bool]:
    """Atomically reject a pending action (TOCTOU-safe, #644).

    Returns ``(action, claimed)``. ``claimed`` is True only for the caller that
    transitioned ``pending`` -> ``rejected``; a losing/duplicate caller gets
    ``False`` so side effects (audit, metrics) fire exactly once.
    """
    from sqlalchemy import update

    result = await db.execute(
        update(PendingAction)
        .where(PendingAction.id == action.id, PendingAction.status == "pending")
        .values(status="rejected")
    )
    await db.commit()
    await db.refresh(action)
    return action, result.rowcount == 1  # type: ignore[attr-defined]


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

        node_name = getattr(node, "hostname", None) or getattr(node, "minion_id", None) or str(action.node_id)
        # Link to the GET confirmation page (safe to prefetch); the page submits a
        # POST to approve/reject. GET no longer mutates state (#644: mail-client
        # prefetch can no longer auto-approve a destructive action).
        confirm_url = f"{api_url}/api/v1/actions/{action.approval_token}"

        body = f"""
<html><body style="font-family:sans-serif;color:#111827">
  <h2 style="color:#D97706">&#9888; Action Approval Required</h2>
  <p><strong>Requested by:</strong> {requested_by}</p>
  <p><strong>Node:</strong> {node_name}</p>
  <p><strong>Action:</strong> {action.action_type}</p>
  <p><strong>Expires:</strong> 15 minutes from request</p>
  <p style="margin-top:24px">
    <a href="{confirm_url}"
       style="background:#2563EB;color:white;padding:10px 20px;border-radius:6px;
              text-decoration:none">Review &amp; decide &rarr;</a>
  </p>
  <p style="color:#6B7280;font-size:12px;margin-top:16px">
    This link opens a confirmation page; no action is taken until you click Approve or Reject there.
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

    await asyncio.to_thread(_send)  # get_event_loop() deprecated in 3.10+; to_thread is safe
