# fleet_platform/services/digest_svc.py
import smtplib
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fleet_platform.models.jenkins_build_event import JenkinsBuildEvent
from fleet_platform.models.node import Node
from fleet_platform.services.platform_settings_svc import (
    DIGEST_RECIPIENTS,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    decrypt_secret,
    get_setting_sync,
)


def get_week_stats(db: Session) -> dict:
    since = datetime.now(UTC) - timedelta(days=7)
    builds = db.execute(select(JenkinsBuildEvent).where(JenkinsBuildEvent.started_at >= since)).scalars().all()

    total = len(builds)
    passed = sum(1 for b in builds if b.result == "SUCCESS")
    failed = sum(1 for b in builds if b.result in ("FAILURE", "UNSTABLE"))

    fail_counts: dict[str, int] = {}
    for b in builds:
        if b.result in ("FAILURE", "UNSTABLE"):
            fail_counts[b.job_name] = fail_counts.get(b.job_name, 0) + 1
    top_failing = sorted(fail_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    total_nodes: int = db.execute(select(func.count(Node.id))).scalar_one()
    online_nodes: int = db.execute(select(func.count(Node.id)).where(Node.status == "online")).scalar_one()

    return {
        "builds_total": total,
        "builds_passed": passed,
        "builds_failed": failed,
        "top_failing_jobs": top_failing,
        "total_nodes": total_nodes,
        "online_nodes": online_nodes,
        "period_start": since.strftime("%Y-%m-%d"),
        "period_end": datetime.now(UTC).strftime("%Y-%m-%d"),
    }


def render_html(stats: dict) -> str:
    top_failing_rows = (
        "".join(
            f"<tr>"
            f'<td style="padding:6px 12px;border-bottom:1px solid #E5E7EB;font-size:13px;color:#111827">{name}</td>'
            f'<td style="padding:6px 12px;border-bottom:1px solid #E5E7EB;text-align:right;color:#DC2626;font-weight:600;font-size:13px">{count}</td>'
            f"</tr>"
            for name, count in stats["top_failing_jobs"]
        )
        or '<tr><td colspan="2" style="padding:8px 12px;font-size:13px;color:#6B7280">No failures this week</td></tr>'
    )

    pass_rate = round(stats["builds_passed"] / stats["builds_total"] * 100) if stats["builds_total"] > 0 else 100

    fail_bg = "#FEF2F2" if stats["builds_failed"] > 0 else "#F9FAFB"
    fail_border = "#FECACA" if stats["builds_failed"] > 0 else "#E5E7EB"
    fail_color = "#DC2626" if stats["builds_failed"] > 0 else "#111827"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Fleet Digest</title></head>
<body style="margin:0;padding:0;background:#F9FAFB;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F9FAFB;padding:32px 16px">
<tr><td>
  <table width="600" cellpadding="0" cellspacing="0"
         style="margin:0 auto;background:#FFFFFF;border-radius:12px;border:1px solid #E5E7EB;overflow:hidden">

    <tr><td style="background:#1D4ED8;padding:24px 32px">
      <p style="margin:0;font-size:12px;font-weight:600;color:#93C5FD;text-transform:uppercase;letter-spacing:0.05em">kri Fleet Platform</p>
      <h1 style="margin:6px 0 0;color:#FFFFFF;font-size:22px;font-weight:700">Weekly Fleet Digest</h1>
      <p style="margin:4px 0 0;color:#BFDBFE;font-size:13px">{stats["period_start"]} — {stats["period_end"]}</p>
    </td></tr>

    <tr><td style="padding:24px 32px">
      <h2 style="margin:0 0 16px;font-size:15px;font-weight:600;color:#111827">Fleet Health</h2>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="50%" style="padding-right:8px">
            <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:#16A34A">{stats["online_nodes"]}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Nodes Online</div>
            </div>
          </td>
          <td width="50%" style="padding-left:8px">
            <div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:#111827">{stats["total_nodes"]}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Total Nodes</div>
            </div>
          </td>
        </tr>
      </table>
    </td></tr>

    <tr><td style="padding:0 32px"><div style="border-top:1px solid #E5E7EB"></div></td></tr>

    <tr><td style="padding:24px 32px">
      <h2 style="margin:0 0 16px;font-size:15px;font-weight:600;color:#111827">Jenkins Builds — Last 7 Days</h2>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td width="33%" style="padding-right:6px">
            <div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:#111827">{stats["builds_total"]}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Total Builds</div>
            </div>
          </td>
          <td width="33%" style="padding:0 3px">
            <div style="background:#F0FDF4;border:1px solid #BBF7D0;border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:#16A34A">{stats["builds_passed"]}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Passed</div>
            </div>
          </td>
          <td width="33%" style="padding-left:6px">
            <div style="background:{fail_bg};border:1px solid {fail_border};border-radius:8px;padding:16px;text-align:center">
              <div style="font-size:32px;font-weight:700;color:{fail_color}">{stats["builds_failed"]}</div>
              <div style="font-size:12px;color:#4B5563;margin-top:4px">Failed</div>
            </div>
          </td>
        </tr>
      </table>
      <div style="margin-top:12px;background:#EFF6FF;border-radius:6px;padding:10px 16px;font-size:13px;color:#1D4ED8;text-align:center">
        Pass rate this week: <strong>{pass_rate}%</strong>
      </div>
    </td></tr>

    <tr><td style="padding:0 32px 24px">
      <h2 style="margin:0 0 12px;font-size:15px;font-weight:600;color:#111827">Top Failing Jobs</h2>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border:1px solid #E5E7EB;border-radius:8px;overflow:hidden">
        <tr style="background:#F9FAFB">
          <th style="padding:8px 12px;text-align:left;font-size:12px;font-weight:600;color:#6B7280;border-bottom:1px solid #E5E7EB">Job</th>
          <th style="padding:8px 12px;text-align:right;font-size:12px;font-weight:600;color:#6B7280;border-bottom:1px solid #E5E7EB">Failures</th>
        </tr>
        {top_failing_rows}
      </table>
    </td></tr>

    <tr><td style="background:#F9FAFB;border-top:1px solid #E5E7EB;padding:16px 32px;text-align:center">
      <p style="margin:0;font-size:12px;color:#6B7280">
        Generated by <strong>kri Fleet Platform</strong> · Weekly digest every Monday 08:00 UTC
      </p>
    </td></tr>

  </table>
</td></tr>
</table>
</body>
</html>"""


def send_digest(db: Session) -> dict:
    smtp_host = get_setting_sync(db, SMTP_HOST)
    if not smtp_host:
        raise ValueError("SMTP host not configured")

    smtp_port = int(get_setting_sync(db, SMTP_PORT) or "587")
    smtp_user = get_setting_sync(db, SMTP_USERNAME)
    smtp_password_raw = get_setting_sync(db, SMTP_PASSWORD)
    smtp_password = decrypt_secret(smtp_password_raw) if smtp_password_raw else ""
    from_addr = get_setting_sync(db, SMTP_FROM) or smtp_user or ""
    recipients_raw = get_setting_sync(db, DIGEST_RECIPIENTS) or ""
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    if not recipients:
        raise ValueError("No digest recipients configured")

    stats = get_week_stats(db)
    html = render_html(stats)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Fleet Digest — Week ending {stats['period_end']}"
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.sendmail(from_addr, recipients, msg.as_string())

    return {"status": "sent", "recipients": len(recipients), **stats}


def send_alert_email(rule: object, alert_event: object) -> None:
    """Send a real-time alert email for a fired AlertEvent.

    Called from alert_svc._maybe_send_alert_email when SMTP is configured.
    Reads SMTP config from platform_settings synchronously.
    """
    from fleet_platform.db.session import get_sync_db  # noqa: PLC0415

    with get_sync_db() as db:
        smtp_host = get_setting_sync(db, SMTP_HOST)
        if not smtp_host:
            return  # SMTP not configured — skip silently

        smtp_port = int(get_setting_sync(db, SMTP_PORT) or "587")
        smtp_user = get_setting_sync(db, SMTP_USERNAME)
        smtp_password_raw = get_setting_sync(db, SMTP_PASSWORD)
        smtp_password = decrypt_secret(smtp_password_raw) if smtp_password_raw else ""
        from_addr = get_setting_sync(db, SMTP_FROM) or smtp_user or ""
        recipients_raw = get_setting_sync(db, DIGEST_RECIPIENTS) or ""
        recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    if not recipients:
        return

    event_type = getattr(rule, "event_type", "alert")
    message = getattr(alert_event, "message", "")
    fired_at = getattr(alert_event, "fired_at", None)
    time_str = fired_at.strftime("%Y-%m-%d %H:%M UTC") if fired_at else "now"

    subject = f"[kri alert] {event_type}: {message[:80]}"
    body_html = f"""
<html><body style="font-family:sans-serif;color:#111827">
  <h2 style="color:#DC2626">⚠ kri Alert</h2>
  <table style="border-collapse:collapse;width:100%;max-width:600px">
    <tr><td style="padding:8px;font-weight:600;color:#4B5563;width:120px">Type</td>
        <td style="padding:8px">{event_type}</td></tr>
    <tr style="background:#F9FAFB"><td style="padding:8px;font-weight:600;color:#4B5563">Message</td>
        <td style="padding:8px">{message}</td></tr>
    <tr><td style="padding:8px;font-weight:600;color:#4B5563">Fired at</td>
        <td style="padding:8px">{time_str}</td></tr>
  </table>
  <p style="margin-top:16px;font-size:12px;color:#9CA3AF">
    Sent by kri fleet management platform.
    Configure alerts in Settings → Alerts.
  </p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, recipients, msg.as_string())
    except Exception:
        pass  # non-fatal — alert was already stored in DB
