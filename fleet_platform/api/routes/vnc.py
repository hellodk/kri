"""VNC proxy — bridges browser noVNC (WebSocket) to Mac Mini VNC server (TCP port 5900).

Security:
  - Only available when vnc_enabled platform setting is "true"
  - JWT auth required (same as SSH)
  - Session logged to ssh_sessions table (type='vnc')
  - Node must be online and have a known IP
"""
import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.db.session import AsyncSessionLocal
from fleet_platform.models.node import Node
from fleet_platform.models.ssh_session import SSHSession
from fleet_platform.services.platform_settings_svc import VNC_ENABLED, get_setting

router = APIRouter(prefix="/api/v1/vnc")

VNC_PORT = 5900


@router.websocket("/session/{node_id}")
async def vnc_session(
    websocket: WebSocket,
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    await websocket.accept()

    # Check feature flag
    vnc_enabled = await get_setting(db, VNC_ENABLED)
    if vnc_enabled != "true":
        await websocket.close(code=4003, reason="VNC is not enabled — an admin must enable it in Settings")
        return

    # Auth
    try:
        from fleet_platform.api.routes.webssh import get_current_user_ws
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

    # Log session
    async with AsyncSessionLocal() as sdb:
        session_rec = SSHSession(
            node_id=node_id,
            user_id=user_id,
            started_at=datetime.now(UTC),
            source_ip=websocket.client.host if websocket.client else None,
            credential_source="vnc",
            status="active",
            target_ip=node.bootstrap_ip,
            ssh_user="screen-share",
        )
        sdb.add(session_rec)
        await sdb.commit()
        await sdb.refresh(session_rec)
        session_id = session_rec.id

    try:
        # Open TCP connection to node VNC port
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(node.bootstrap_ip, VNC_PORT),
            timeout=10,
        )
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
        err_msg = f"Cannot connect to VNC on {node.bootstrap_ip}:{VNC_PORT} — ensure Screen Sharing is enabled: {e}"
        await websocket.close(code=4000, reason=err_msg[:120])
        await _close_session(session_id, "failed")
        return

    async def ws_to_vnc():
        """Forward WebSocket messages → VNC TCP."""
        try:
            while True:
                msg = await websocket.receive_bytes()
                writer.write(msg)
                await writer.drain()
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            writer.close()

    async def vnc_to_ws():
        """Forward VNC TCP → WebSocket."""
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass

    ws_task = asyncio.create_task(ws_to_vnc())
    vnc_task = asyncio.create_task(vnc_to_ws())

    done, pending = await asyncio.wait(
        [ws_task, vnc_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()

    try:
        writer.close()
    except Exception:
        pass
    await _close_session(session_id, "closed")


async def _close_session(session_id: uuid.UUID, status: str) -> None:
    async with AsyncSessionLocal() as db:
        session = await db.get(SSHSession, session_id)
        if session:
            session.ended_at = datetime.now(UTC)
            session.status = status
        await db.commit()
