"""TOFU (Trust-On-First-Use) SSH host key management."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.node import Node

logger = logging.getLogger(__name__)

# Known OpenSSH public-key algorithm identifiers accepted in a known_hosts file.
_KNOWN_SSH_ALGS = frozenset(
    {
        "ssh-ed25519",
        "ssh-rsa",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "ssh-dss",
    }
)


def to_known_hosts_token(stored: str) -> str | None:
    """Return a valid known_hosts token ``<alg> <base64>`` from a stored key value.

    Handles two legacy/current storage shapes:

    * **Native form** – the value is already ``<alg> <base64>`` (or with an
      optional comment).  The first two whitespace-separated tokens are returned
      directly.
    * **Legacy base64-wrapped form** – WebSSH used to store
      ``base64(export_public_key("openssh"))`` which produced an opaque blob
      rather than a parseable token.  The value is decoded and the algorithm +
      key token is extracted.

    Returns ``None`` when the value cannot be parsed into a valid token.
    """
    if not stored:
        return None

    candidate = stored.strip()

    # Fast path: already in native '<alg> <base64>' form.
    parts = candidate.split()
    if len(parts) >= 2 and parts[0] in _KNOWN_SSH_ALGS:
        return f"{parts[0]} {parts[1]}"

    # Slow path: try decoding as a base64-wrapped OpenSSH public key line.
    try:
        decoded = base64.b64decode(candidate).decode("ascii")
        parts = decoded.strip().split()
        if len(parts) >= 2 and parts[0] in _KNOWN_SSH_ALGS:
            return f"{parts[0]} {parts[1]}"
    except Exception:
        pass

    return None


def pinned_known_hosts_file(host: str, stored_key: str | None) -> str | None:
    """Write a temp known_hosts file pinning *host* to its stored key (#1046).

    Passing the returned path as asyncssh's ``known_hosts`` makes a key mismatch
    fail during the SSH handshake — BEFORE any credential is transmitted —
    instead of after authentication (detection, not prevention).

    Returns the temp file path (caller must unlink it), or ``None`` when no
    parseable stored key exists (first contact → TOFU flow still applies).
    """
    import os
    import tempfile

    token = to_known_hosts_token(stored_key or "")
    if not token:
        return None

    fd, path = tempfile.mkstemp(prefix="kri-kh-", suffix=".known_hosts")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"{host} {token}\n")
    except Exception:
        os.unlink(path)
        return None
    return path


async def verify_or_store_host_key(
    node: Node,
    host_key_b64: str,
    db: AsyncSession,
    user_id: str | None = None,
) -> bool:
    """TOFU check for SSH host key.

    - First connection: stores the key, returns True.
    - Subsequent connections: returns True if key matches stored.
    - Mismatch: logs a security event, returns False (caller must abort).
    """
    if not node.ssh_host_key:
        node.ssh_host_key = host_key_b64
        await db.commit()
        logger.info("TOFU: stored host key for node %s (%s)", node.id, node.hostname)
        return True

    if node.ssh_host_key == host_key_b64:
        return True

    # Cross-format comparison: a legacy base64-wrapped key and its decoded
    # native form must compare as equal to avoid spurious MITM warnings during
    # the migration from the old storage format to the new one (#840).
    norm_stored = to_known_hosts_token(node.ssh_host_key)
    norm_incoming = to_known_hosts_token(host_key_b64)
    if norm_stored is not None and norm_incoming is not None and norm_stored == norm_incoming:
        return True

    logger.warning(
        "SSH host key mismatch for node %s (%s) — possible MitM attack",
        node.id,
        node.hostname,
    )
    # Import SecurityEvent here to avoid circular imports
    from fleet_platform.models.ssh_session import SecurityEvent  # noqa: PLC0415

    user_uuid: uuid.UUID | None = None
    if user_id is not None:
        try:
            user_uuid = uuid.UUID(user_id)
        except (ValueError, AttributeError):
            user_uuid = None

    event = SecurityEvent(
        node_id=node.id,
        user_id=user_uuid,
        event_type="ssh_host_key_mismatch",
        severity="critical",
        detail=(f"Expected key: {node.ssh_host_key[:40]}... Got key: {host_key_b64[:40]}..."),
        created_at=datetime.now(UTC),
    )
    db.add(event)
    await db.commit()
    return False
