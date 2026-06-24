"""Resolve effective SSH credentials for a node.

Priority chain (first match wins):
  1. Node-level credential   (node.credential_id -> Credential)
  2. Group credential        (member group, highest credential_priority then
                              name; credential_id deref)
  3. Controller key          (node was bootstrapped — ssh_host_key set — and
                              ~/.kri/id_rsa exists)
  4. Global default          (platform settings: SSH_USERNAME / SSH_PASSWORD)

Design intent: tiers 1 and 2 are explicit operator-set credentials and always
win.  Tier 3 applies only to nodes that have been bootstrapped (TOFU host-key
recorded) and have no explicit override; the controller private key was
installed on the node during bootstrap.  Tier 4 is the legacy password
fallback for nodes that have never been bootstrapped.

Single secret-resolution path (#748 — ARC-4): node/group SSH creds live solely
in the first-class ``Credential`` store, referenced by ``credential_id``. The
deprecated inline ``ssh_username`` / ``ssh_password_enc`` / ``ssh_key_enc`` /
``ssh_auth_mode`` columns are **no longer read** here — migration 055 copied
them into the Credential store, 058 NULLed them, and 061 drops them. Eliminating
the inline read closes the dual secret-resolution path: there is now exactly one
place a node/group secret can come from (the Credential store), plus the
controller/global platform tiers, which are not per-row secrets.

Callers that *require* a usable secret (WebSSH, VNC, password-mode bootstrap)
should use :func:`require_usable_node_credentials` /
:func:`require_usable_node_credentials_sync`, which raise
:class:`NoUsableCredentialError` instead of silently returning a credential-less
result — the pre-#748 behaviour quietly fell back to the inline columns.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.credential import Credential
from fleet_platform.models.group import Group, GroupMember
from fleet_platform.models.node import Node
from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.services.platform_settings_svc import (
    SSH_PASSWORD,
    SSH_USERNAME,
    _fernet,
    decrypt_secret,
)
from fleet_platform.services.ssh_keypair import _DEFAULT_PRIV

logger = logging.getLogger(__name__)


class NoUsableCredentialError(RuntimeError):
    """Raised when an SSH credential is required but none can be resolved.

    The deprecated inline ``ssh_*`` columns are no longer consulted (#748 —
    ARC-4). A node with no node/group ``credential_id`` (or one pointing at a
    secret-less Credential), no controller key, and no global password has no
    usable secret. Pre-#748 such a node would silently fall back to the inline
    columns — a second secret path. Callers that *require* a credential must now
    fail loudly via :func:`require_usable_node_credentials` rather than attempt a
    connection with no secret.
    """


def has_usable_secret(creds: dict) -> bool:
    """True if resolved ``creds`` carry a usable secret for their ``auth_mode`` (#701).

    Used by credential-required actions (WebSSH, VNC, password-mode bootstrap) to
    fail loudly instead of silently attempting a connection with no secret.
    """
    if creds.get("auth_mode") == "key":
        return bool(creds.get("ssh_key"))
    return bool(creds.get("ssh_password"))


def _read_controller_key() -> str:
    """Return the controller private key (~/.kri/id_rsa) or '' if absent/unreadable."""
    try:
        return _DEFAULT_PRIV.read_text()
    except OSError:
        return ""


def _decrypt_or_blank(label: str, ident, field: str, ciphertext: str | None) -> str:
    if not ciphertext:
        return ""
    try:
        return decrypt_secret(ciphertext)
    except Exception as exc:
        logger.warning("Fernet decryption failed for %s %s field %s: %s", label, ident, field, exc)
        return ""


def _credential_to_creds(cred: Credential, source: str) -> dict:
    """Map a :class:`Credential` row onto the resolved-creds dict shape.

    ``kind='ssh_key'`` -> key auth (secret is the private key); any other kind
    (``username_password`` / ``token``) -> password auth (secret is the
    password). ``last_used_at`` is touched best-effort for rotation/audit
    visibility (#698) — it persists only if the caller commits the session.
    """
    secret = _decrypt_or_blank("credential", cred.id, "secret", cred.secret_enc)
    try:
        cred.last_used_at = datetime.now(UTC)
    except Exception:  # pragma: no cover — best-effort, never block resolution
        pass
    if cred.kind == "ssh_key":
        return {
            "ssh_user": cred.username or "",
            "ssh_password": "",
            "ssh_key": secret,
            "auth_mode": "key",
            "credential_source": source,
        }
    return {
        "ssh_user": cred.username or "",
        "ssh_password": secret,
        "ssh_key": "",
        "auth_mode": "password",
        "credential_source": source,
    }


def _primary_group_stmt(node_id):
    """Member group that carries a Credential FK, highest priority then name.

    Ordering by ``credential_priority DESC, name ASC`` makes the multi-group
    tiebreak deterministic (#699); alphabetical name is the stable final
    tiebreak, so all-default-priority fleets behave exactly as before. Only
    groups with a ``credential_id`` are eligible — inline ``ssh_*`` columns are
    no longer a credential source (#748).
    """
    return (
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.node_id == node_id)
        .where(Group.credential_id.isnot(None))
        .order_by(Group.credential_priority.desc(), Group.name.asc())
        .limit(1)
    )


async def resolve_node_credentials(node: Node, db: AsyncSession) -> dict:
    """Return resolved SSH credentials for a node.

    Returns dict with keys: ssh_user, ssh_password, ssh_key, auth_mode,
    credential_source ('node' | 'group:<name>' | 'controller' | 'global')
    """
    # 1. Node-level credential — Credential store only (#748: no inline fallback).
    #    An FK pointing at a secret-less Credential (#704 birth defect) is not a
    #    real credential: skip it and fall through rather than short-circuiting.
    if node.credential_id:
        cred = await db.get(Credential, node.credential_id)
        if cred is not None:
            creds = _credential_to_creds(cred, "node")
            if has_usable_secret(creds):
                return creds

    # 2. Primary group credential (highest priority, then name).
    group = (await db.execute(_primary_group_stmt(node.id))).scalar_one_or_none()
    if group is not None and group.credential_id:
        cred = await db.get(Credential, group.credential_id)
        if cred is not None:
            creds = _credential_to_creds(cred, f"group:{group.name}")
            if has_usable_secret(creds):
                return creds

    # 3. Controller key — node was bootstrapped (ssh_host_key set) and key file exists
    if node.ssh_host_key:
        controller_key = _read_controller_key()
        if controller_key:
            ssh_user = await _get_global_setting(db, SSH_USERNAME) or "admin"
            return {
                "ssh_user": ssh_user,
                "ssh_password": "",
                "ssh_key": controller_key,
                "auth_mode": "key",
                "credential_source": "controller",
            }

    # 4. Global fallback from platform settings
    ssh_user = await _get_global_setting(db, SSH_USERNAME) or "admin"
    ssh_password = await _get_global_setting(db, SSH_PASSWORD, encrypted=True)

    return {
        "ssh_user": ssh_user,
        "ssh_password": ssh_password,
        "ssh_key": "",
        "auth_mode": "password",
        "credential_source": "global",
    }


def resolve_node_credentials_sync(node: Node, db) -> dict:
    """Synchronous twin of :func:`resolve_node_credentials` for the Celery worker.

    The playbook worker runs on a sync SQLAlchemy ``Session`` (``get_sync_db``),
    so it cannot await the async resolver. This mirrors the same
    node → primary-group → controller → global priority chain and returns the
    identical dict shape, including ``credential_source`` (#279, #349, #698).
    """
    # 1. Node-level credential — Credential store only (#748: no inline fallback).
    #    An FK pointing at a secret-less Credential (#704 birth defect) is not a
    #    real credential: skip it and fall through rather than short-circuiting.
    if node.credential_id:
        cred = db.get(Credential, node.credential_id)
        if cred is not None:
            creds = _credential_to_creds(cred, "node")
            if has_usable_secret(creds):
                return creds

    # 2. Primary group credential (highest priority, then name).
    group = db.execute(_primary_group_stmt(node.id)).scalar_one_or_none()
    if group is not None and group.credential_id:
        cred = db.get(Credential, group.credential_id)
        if cred is not None:
            creds = _credential_to_creds(cred, f"group:{group.name}")
            if has_usable_secret(creds):
                return creds

    # 3. Controller key — node was bootstrapped (ssh_host_key set) and key file exists
    if node.ssh_host_key:
        controller_key = _read_controller_key()
        if controller_key:
            return {
                "ssh_user": _get_global_setting_sync(db, SSH_USERNAME) or "admin",
                "ssh_password": "",
                "ssh_key": controller_key,
                "auth_mode": "key",
                "credential_source": "controller",
            }

    # 4. Global fallback from platform settings
    return {
        "ssh_user": _get_global_setting_sync(db, SSH_USERNAME) or "admin",
        "ssh_password": _get_global_setting_sync(db, SSH_PASSWORD, encrypted=True),
        "ssh_key": "",
        "auth_mode": "password",
        "credential_source": "global",
    }


def _no_usable_secret_message(node: Node) -> str:
    minion = getattr(node, "minion_id", None) or getattr(node, "id", "<unknown>")
    return (
        f"No usable SSH credential for node {minion}: link a Credential via "
        "credential_id (node- or group-level), bootstrap the node, or configure "
        "global SSH credentials. Inline ssh_* columns are no longer a credential "
        "source (#748)."
    )


async def require_usable_node_credentials(node: Node, db: AsyncSession) -> dict:
    """Resolve credentials and raise if none carry a usable secret (#748).

    Use from credential-required actions (WebSSH, VNC, password-mode bootstrap)
    that must fail loudly. This is the explicit replacement for the old inline
    read-fallback: a node with no resolvable secret now raises
    :class:`NoUsableCredentialError` instead of silently degrading.
    """
    creds = await resolve_node_credentials(node, db)
    if not has_usable_secret(creds):
        raise NoUsableCredentialError(_no_usable_secret_message(node))
    return creds


def require_usable_node_credentials_sync(node: Node, db) -> dict:
    """Synchronous twin of :func:`require_usable_node_credentials` (#748)."""
    creds = resolve_node_credentials_sync(node, db)
    if not has_usable_secret(creds):
        raise NoUsableCredentialError(_no_usable_secret_message(node))
    return creds


def _get_global_setting_sync(db, key: str, encrypted: bool = False) -> str:
    row = db.execute(select(PlatformSetting).where(PlatformSetting.key == key)).scalar_one_or_none()
    if not row or not row.value:
        return ""
    if encrypted and row.is_encrypted:
        try:
            return _fernet().decrypt(row.value.encode()).decode()
        except Exception as exc:
            logger.warning("Fernet decryption failed for global platform setting %s: %s", key, exc)
            return ""
    return row.value or ""


async def _get_global_setting(db: AsyncSession, key: str, encrypted: bool = False) -> str:
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
    row = result.scalar_one_or_none()
    if not row or not row.value:
        return ""
    if encrypted and row.is_encrypted:
        try:
            return _fernet().decrypt(row.value.encode()).decode()
        except Exception as exc:
            logger.warning(
                "Fernet decryption failed for global platform setting %s: %s",
                key,
                exc,
            )
            return ""
    return row.value or ""


async def node_has_group(node_id, db: AsyncSession) -> bool:
    """Return True if the node belongs to at least one group."""
    result = await db.execute(select(GroupMember).where(GroupMember.node_id == node_id).limit(1))
    return result.scalar_one_or_none() is not None


async def nodes_using_credential(credential_id, db: AsyncSession) -> list[tuple[Node, str]]:
    """Return ``(node, source)`` for every node whose *resolved* credential is ``credential_id`` (#700).

    Resolution-aware: a node counts if its node-level FK points at the credential
    (``source='node'``), or — when the node has no node-level credential — its
    primary credential-bearing group (highest ``credential_priority``, then name)
    points at it (``source='group:<name>'``). This is the read-only audit/rotation
    view; it deliberately ignores controller/global tiers (not Credential rows).
    """
    results: list[tuple[Node, str]] = []
    seen: set = set()

    direct = (await db.execute(select(Node).where(Node.credential_id == credential_id))).scalars().all()
    for n in direct:
        results.append((n, "node"))
        seen.add(n.id)

    # Candidate nodes: members of a group that references this credential, with no
    # node-level credential of their own. Confirm this credential's group actually
    # wins the priority tiebreak for each candidate before counting it.
    candidates = (
        (
            await db.execute(
                select(Node)
                .join(GroupMember, GroupMember.node_id == Node.id)
                .join(Group, Group.id == GroupMember.group_id)
                .where(Group.credential_id == credential_id)
                .where(Node.credential_id.is_(None))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    for n in candidates:
        if n.id in seen:
            continue
        group = (await db.execute(_primary_group_stmt(n.id))).scalar_one_or_none()
        if group is not None and group.credential_id == credential_id:
            results.append((n, f"group:{group.name}"))
            seen.add(n.id)

    return results
