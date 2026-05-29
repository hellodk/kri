"""WebSSH proxy — browser xterm.js <-> asyncssh <-> Mac Mini.

Security model:
  - Credentials resolved server-side, never sent to browser
  - Full session recording stored in DB
  - Real security enforced at OS level (see note below)

# Security note: command-level filtering in the WebSocket handler cannot reliably
# block malicious input — shell features (backticks, $(), eval, alternate paths)
# trivially bypass string matching. Real security is enforced at the OS level:
# sudo restrictions, SELinux/AppArmor profiles, and restricted shells on fleet nodes.
# The previous blocklist was removed (issue #118) to avoid false confidence.
"""
import asyncio
import base64
import logging
import uuid
from datetime import UTC, datetime

import asyncssh
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import (
    TokenExpiredError,
    TokenInvalidError,
    decode_token,
    require_role,
)
from fleet_platform.db.session import AsyncSessionLocal
from fleet_platform.models.node import Node
from fleet_platform.models.ssh_session import SecurityEvent, SessionRecording, SSHSession
from fleet_platform.services.ssh_connection_cache import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ssh")


async def get_current_user_ws(token: str) -> dict:
    """Verify JWT token for WebSocket connections (token from query param)."""
    try:
        claims = decode_token(token)
    except TokenExpiredError:
        raise ValueError("Token has expired")
    except TokenInvalidError:
        raise ValueError("Invalid token")
    if claims.get("type") != "access":
        raise ValueError("Refresh tokens cannot access this endpoint")
    return claims


class SSHProxySession:
    """Manages one WebSocket <-> SSH connection with recording."""

    def __init__(self, ws: WebSocket, session_id: uuid.UUID, max_mins: int = 60):
        self.ws = ws
        self.session_id = session_id
        self.max_mins = max_mins
        self._ssh_conn: asyncssh.SSHClientConnection | None = None
        self._ssh_process: asyncssh.SSHClientProcess | None = None
        self._cmd_buffer = ""          # accumulates keystrokes until Enter
        self._recording_chunks: list[tuple[str, datetime]] = []
        self._chunk_index = 0
        self._alert_count = 0
        self._owns_connection = True   # False when connection comes from cache

    async def send_to_browser(self, data: bytes) -> None:
        """Send terminal output to browser and record it."""
        text = data.decode("utf-8", errors="replace")
        self._recording_chunks.append((text, datetime.now(UTC)))
        if len(self._recording_chunks) >= 20:
            await self._flush_recording()
        try:
            await self.ws.send_text(text)
        except Exception as e:
            logger.debug("send_to_browser: ws send failed (client may have disconnected): %s", e)

    async def _flush_recording(self) -> None:
        if not self._recording_chunks:
            return
        chunks = self._recording_chunks[:]
        self._recording_chunks.clear()
        async with AsyncSessionLocal() as db:
            for text, ts in chunks:
                db.add(SessionRecording(
                    session_id=self.session_id,
                    chunk_index=self._chunk_index,
                    data=base64.b64encode(text.encode()).decode(),
                    recorded_at=ts,
                ))
                self._chunk_index += 1
            await db.commit()

    async def handle_keystroke(self, key: str) -> bool:
        """Process a keystroke. Return False if the SSH process should be disconnected."""
        if not self._ssh_process:
            return True

        # Accumulate printable chars into command buffer
        if key in ("\r", "\n"):
            # Enter — send through; OS-level restrictions enforce security
            self._cmd_buffer = ""
            self._ssh_process.stdin.write("\r")
        elif key == "\x7f" or key == "\x08":
            # Backspace
            if self._cmd_buffer:
                self._cmd_buffer = self._cmd_buffer[:-1]
            self._ssh_process.stdin.write(key)
        elif key == "\x03":
            # Ctrl+C — clear buffer, pass through
            self._cmd_buffer = ""
            self._ssh_process.stdin.write(key)
        elif len(key) == 1 and key.isprintable():
            self._cmd_buffer += key
            self._ssh_process.stdin.write(key)
        else:
            # Control sequence, arrow keys, etc — pass through
            self._ssh_process.stdin.write(key)

        return True

    async def _log_security_event(self, event_type: str, command: str, severity: str) -> None:
        async with AsyncSessionLocal() as db:
            db.add(SecurityEvent(
                session_id=self.session_id,
                event_type=event_type,
                command=command[:500],
                severity=severity,
                created_at=datetime.now(UTC),
            ))
            # Increment alert count on session
            session = await db.get(SSHSession, self.session_id)
            if session:
                session.alert_count = self._alert_count
            await db.commit()

    async def close(self, status: str = "closed") -> None:
        await self._flush_recording()
        if self._ssh_process:
            try:
                self._ssh_process.close()
            except Exception as e:
                logger.debug("close: SSH process close failed: %s", e)
        if self._ssh_conn and self._owns_connection:
            try:
                self._ssh_conn.close()
            except Exception as e:
                logger.debug("close: SSH connection close failed: %s", e)
        # Update session end
        async with AsyncSessionLocal() as db:
            session = await db.get(SSHSession, self.session_id)
            if session:
                session.ended_at = datetime.now(UTC)
                session.status = status
                session.alert_count = self._alert_count
            await db.commit()


@router.websocket("/session/{node_id}")
async def webssh_session(
    websocket: WebSocket,
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """WebSocket endpoint for browser-based SSH sessions."""
    await websocket.accept()

    # Auth — verify JWT from query param
    try:
        token = websocket.query_params.get("token", "")
        if not token:
            await websocket.close(code=4001, reason="Missing auth token")
            return
        claims = await get_current_user_ws(token)
        user_id = uuid.UUID(claims["sub"])
    except Exception:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    # Load node
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        await websocket.close(code=4004, reason="Node not found")
        return

    if not node.bootstrap_ip:
        await websocket.close(code=4000, reason="Node has no known IP — bootstrap first")
        return

    # Resolve credentials server-side
    from fleet_platform.services.credential_resolver import resolve_node_credentials
    creds = await resolve_node_credentials(node, db)

    # Create session record
    session_rec = SSHSession(
        node_id=node_id,
        user_id=user_id,
        started_at=datetime.now(UTC),
        source_ip=websocket.client.host if websocket.client else None,
        credential_source=creds["credential_source"],
        status="active",
        target_ip=node.bootstrap_ip,
        ssh_user=creds["ssh_user"],
    )
    db.add(session_rec)
    await db.commit()
    await db.refresh(session_rec)
    session_id = session_rec.id

    # Get session max mins from group (default 60 if not configured)
    max_mins = 60
    from fleet_platform.models.group import Group, GroupMember
    group_result = await db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.node_id == node_id)
        .order_by(Group.name.asc())
        .limit(1)
    )
    primary_group = group_result.scalar_one_or_none()
    if primary_group and primary_group.session_max_mins:
        max_mins = primary_group.session_max_mins

    proxy = SSHProxySession(websocket, session_id, max_mins)

    # Send welcome banner to browser
    node_label = (node.hostname or node.minion_id or str(node_id))[:30]
    ssh_user_label = (creds["ssh_user"] or "unknown")[:30]
    cred_source_label = (creds["credential_source"] or "unknown")[:30]
    max_mins_str = str(max_mins)
    banner = (
        f"\r\n\033[36m+-- kri PAM ----------------------------------------+\033[0m\r\n"
        f"\033[36m|\033[0m  Node:    {node_label:<38}\033[36m|\033[0m\r\n"
        f"\033[36m|\033[0m  User:    {ssh_user_label:<38}\033[36m|\033[0m\r\n"
        f"\033[36m|\033[0m  Source:  {cred_source_label:<38}\033[36m|\033[0m\r\n"
        f"\033[36m|\033[0m  Max session: {max_mins_str} minutes"
        f"{' ' * (29 - len(max_mins_str))}\033[36m|\033[0m\r\n"
        f"\033[36m|\033[0m  Session is recorded and audited               \033[36m|\033[0m\r\n"
        f"\033[36m+---------------------------------------------------+\033[0m\r\n\r\n"
    )
    await websocket.send_text(banner)

    # Log session_start security event
    async with AsyncSessionLocal() as ev_db:
        ev_db.add(SecurityEvent(
            session_id=session_id,
            node_id=node_id,
            user_id=user_id,
            event_type="session_start",
            severity="info",
            detail=f"source_ip={session_rec.source_ip} credential_source={creds['credential_source']}",
            created_at=datetime.now(UTC),
        ))
        await ev_db.commit()

    # Guard: if credentials could not be decrypted the password will be empty string.
    # Surface this clearly in the terminal rather than letting SSH auth silently fail.
    if creds["auth_mode"] == "password" and not creds.get("ssh_password"):
        await proxy.send_to_browser(
            b"\r\n\x1b[31m[SSH Error] Credentials could not be decrypted.\x1b[0m\r\n"
            b"\x1b[33mThe SSH password stored for this node was encrypted with a different\r\n"
            b"JWT_SECRET than the one currently in .env.docker.\r\n"
            b"\r\nFix: go to Node \xe2\x86\x92 Secrets tab and re-enter the SSH password.\x1b[0m\r\n"
        )
        await proxy._flush_recording()
        await proxy.close(status="failed")
        return

    try:
        # Connect to node via asyncssh (with connection cache)
        connect_kwargs: dict = dict(
            host=node.bootstrap_ip,
            port=22,
            username=creds["ssh_user"],
            known_hosts=None,
            connect_timeout=15,
        )
        if creds["auth_mode"] == "key" and creds.get("ssh_key"):
            import os
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
                f.write(creds["ssh_key"])
                key_path = f.name
            os.chmod(key_path, 0o600)
            try:
                connect_kwargs["client_keys"] = [key_path]
                proxy._ssh_conn = await get_connection(
                    host=node.bootstrap_ip,
                    port=22,
                    username=creds["ssh_user"],
                    connect_kwargs=connect_kwargs,
                )
                proxy._owns_connection = False  # connection is shared via cache
            finally:
                os.unlink(key_path)
        else:
            connect_kwargs["password"] = creds["ssh_password"]
            proxy._ssh_conn = await get_connection(
                host=node.bootstrap_ip,
                port=22,
                username=creds["ssh_user"],
                connect_kwargs=connect_kwargs,
            )
            proxy._owns_connection = False  # connection is shared via cache

        if proxy._ssh_conn is None:
            raise RuntimeError("SSH proxy connection was not established")

        # TOFU: verify/store SSH host key
        server_host_key = proxy._ssh_conn.get_server_host_key()
        if server_host_key is not None:
            key_bytes = server_host_key.export_public_key("openssh")
            if isinstance(key_bytes, str):
                key_bytes = key_bytes.encode()
            key_b64 = base64.b64encode(key_bytes).decode()
            from fleet_platform.services.ssh_host_key_svc import verify_or_store_host_key
            key_ok = await verify_or_store_host_key(node, key_b64, db, user_id=str(user_id))
            if not key_ok:
                proxy._ssh_conn.close()
                raise RuntimeError(
                    "SSH host key mismatch — connection refused. "
                    "Possible man-in-the-middle attack. Contact your administrator."
                )

        proxy._ssh_process = await proxy._ssh_conn.create_process(
            term_type="xterm-256color",
            request_pty=True,
        )

        # Pump stdout from SSH to browser
        async def read_ssh():
            try:
                async for chunk in proxy._ssh_process.stdout:
                    if isinstance(chunk, str):
                        chunk = chunk.encode()
                    await proxy.send_to_browser(chunk)
            except Exception as e:
                logger.debug("read_ssh: SSH stdout pump ended: %s", e)

        asyncio.create_task(read_ssh())

        # Session timeout
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max_mins * 60

        # Read keystrokes from browser, forward to SSH
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                timeout_msg = (
                    f"\r\n\033[33m[TIMEOUT] Session timed out (max {max_mins} min)\033[0m\r\n"
                )
                await proxy.send_to_browser(timeout_msg.encode())
                await proxy.close("timed_out")
                await websocket.close()
                return

            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=min(remaining, 30)
                )
                if not await proxy.handle_keystroke(data):
                    break
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break

    except asyncssh.DisconnectError as e:
        err = f"\r\n\033[31mSSH error: {e}\033[0m\r\n"
        await proxy.send_to_browser(err.encode())
    except Exception as e:
        err = f"\r\n\033[31mConnection failed: {e}\033[0m\r\n"
        try:
            await proxy.send_to_browser(err.encode())
        except Exception:
            pass
    finally:
        await proxy.close()


# ── Session list and recording endpoints ──────────────────────────────────────

@router.get("/sessions")
async def list_sessions(
    node_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin", "operator")),
):
    """List SSH sessions with optional filters."""
    q = select(SSHSession).order_by(SSHSession.started_at.desc()).limit(limit)
    if node_id:
        q = q.where(SSHSession.node_id == node_id)
    if status:
        q = q.where(SSHSession.status == status)
    result = await db.execute(q)
    sessions = result.scalars().all()
    return {"items": [
        {
            "id": str(s.id),
            "node_id": str(s.node_id),
            "user_id": str(s.user_id) if s.user_id else None,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "source_ip": s.source_ip,
            "credential_source": s.credential_source,
            "status": s.status,
            "alert_count": s.alert_count,
            "target_ip": s.target_ip,
            "ssh_user": s.ssh_user,
        }
        for s in sessions
    ]}


@router.get("/sessions/{session_id}/recording")
async def get_session_recording(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin", "operator")),
):
    """Return session recording chunks for replay."""
    result = await db.execute(
        select(SessionRecording)
        .where(SessionRecording.session_id == session_id)
        .order_by(SessionRecording.chunk_index.asc())
    )
    chunks = result.scalars().all()
    return {
        "session_id": str(session_id),
        "chunks": [
            {"index": c.chunk_index, "data": c.data, "recorded_at": c.recorded_at}
            for c in chunks
        ],
    }


@router.get("/events")
async def list_security_events(
    node_id: uuid.UUID | None = None,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin", "operator")),
):
    """List security events (blocks, alerts, auth failures)."""
    q = select(SecurityEvent).order_by(SecurityEvent.created_at.desc()).limit(limit)
    if node_id:
        q = q.where(SecurityEvent.node_id == node_id)
    if event_type:
        q = q.where(SecurityEvent.event_type == event_type)
    result = await db.execute(q)
    events = result.scalars().all()
    return {"items": [
        {
            "id": str(e.id),
            "session_id": str(e.session_id) if e.session_id else None,
            "node_id": str(e.node_id) if e.node_id else None,
            "event_type": e.event_type,
            "command": e.command,
            "severity": e.severity,
            "detail": e.detail,
            "created_at": e.created_at,
        }
        for e in events
    ]}
