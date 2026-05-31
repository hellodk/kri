"""VNC proxy — bridges browser noVNC (WebSocket) to Mac Mini VNC server (TCP port 5900).

Security:
  - Only available when vnc_enabled platform setting is "true"
  - JWT auth required (same as SSH)
  - Session logged to ssh_sessions table (type='vnc')
  - Node must be online and have a known IP
  - RFB authentication is performed server-side using the node's stored VNC password
"""
import asyncio
import struct
import uuid
from datetime import UTC, datetime

from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES as _TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.db.session import AsyncSessionLocal
from fleet_platform.models.node import Node
from fleet_platform.models.ssh_session import SSHSession
from fleet_platform.services.platform_settings_svc import VNC_ENABLED, decrypt_secret, get_setting

router = APIRouter(prefix="/api/v1/vnc")

VNC_PORT = 5900


def _vnc_des_key(password: str) -> bytes:
    """Return the 8-byte DES key used by VNC RFB auth.

    VNC uses standard DES with a peculiar key encoding: the bits within each
    key byte are reversed (LSB becomes MSB).  A password longer than 8 chars
    is truncated; shorter passwords are right-padded with NUL bytes.
    """
    raw = password.encode("utf-8")[:8].ljust(8, b"\x00")
    return bytes(int(f"{b:08b}"[::-1], 2) for b in raw)


async def _rfb_auth(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    password: str | None,
) -> bool:
    """Perform the RFB handshake server-side.

    Supports:
      - Security type 1 (None) — accepted unconditionally.
      - Security type 2 (VNC Auth) — DES challenge/response using the stored password.

    Returns True when the server grants access, False on any failure.
    The caller must close the WebSocket and writer on False.
    """
    # --- Version negotiation ---
    server_ver = await reader.read(12)
    if len(server_ver) < 12:
        return False
    # Always speak RFB 3.8 — broadly compatible and required for type negotiation
    writer.write(b"RFB 003.008\n")
    await writer.drain()

    # --- Security type list ---
    header = await reader.read(1)
    if not header:
        return False
    n_types = header[0]
    if n_types == 0:
        # Server sent an error (RFB 3.8 error path)
        return False
    sec_types_bytes = await reader.read(n_types)
    if len(sec_types_bytes) < n_types:
        return False
    sec_types = list(sec_types_bytes)

    # Prefer type 1 (None auth) — no password needed
    if 1 in sec_types:
        writer.write(b"\x01")
        await writer.drain()
        # RFB 3.8 sends a 4-byte SecurityResult even for type 1
        result_bytes = await reader.read(4)
        if len(result_bytes) < 4:
            return True  # older servers skip SecurityResult for type 1
        status = struct.unpack(">I", result_bytes)[0]
        return status == 0

    # Type 2 (VNC Auth) — require a password
    if 2 in sec_types:
        if not password:
            # Cannot complete VNC auth without password — fall through to "no supported type"
            pass
        else:
            writer.write(b"\x02")
            await writer.drain()

            challenge = await reader.read(16)
            if len(challenge) < 16:
                return False

            key = _vnc_des_key(password)
            # DES/ECB — encrypt two 8-byte blocks independently.
            # Use TripleDES(key * 3) which degenerates to plain DES when all three
            # sub-keys are identical — standard VNC RFB behaviour.
            cipher = Cipher(_TripleDES(key * 3), modes.ECB())  # nosec B305 — VNC RFB protocol requires DES/ECB
            encryptor = cipher.encryptor()
            response = encryptor.update(challenge[:8]) + encryptor.update(challenge[8:]) + encryptor.finalize()

            writer.write(response)
            await writer.drain()

            result_bytes = await reader.read(4)
            if len(result_bytes) < 4:
                return False
            status = struct.unpack(">I", result_bytes)[0]
            return status == 0

    # No supported security type — log a diagnostic to help operators
    import logging
    _log = logging.getLogger(__name__)
    _log.warning(
        "_rfb_auth: server offered security types %s — none supported. "
        "macOS Screen Sharing uses type 30 (Apple Remote Desktop) by default. "
        "To enable VNC type-2 auth: System Settings → Sharing → Screen Sharing → "
        "check 'VNC viewers may control screen with password' and set a password, "
        "then store it in kri Node → Secrets → VNC Password.",
        sec_types,
    )
    return False


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

    # Retrieve stored VNC password (if any)
    vnc_password: str | None = None
    if node.vnc_password_enc:
        try:
            vnc_password = decrypt_secret(node.vnc_password_enc)
        except Exception:
            pass  # proceed — server may not require auth

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

    # Perform RFB server-side handshake before bridging the WebSocket
    try:
        auth_ok = await asyncio.wait_for(
            _rfb_auth(reader, writer, vnc_password),
            timeout=15,
        )
    except asyncio.TimeoutError:
        auth_ok = False

    if not auth_ok:
        try:
            writer.close()
        except Exception:
            pass
        if vnc_password is None:
            await websocket.close(
                code=4005,
                reason="VNC requires a password — go to Node → Secrets → VNC Password",
            )
        else:
            await websocket.close(code=4006, reason="VNC authentication failed")
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
