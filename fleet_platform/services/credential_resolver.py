"""Resolve effective SSH credentials for a node.

Priority chain (first match wins):
  1. Node-level override  (node.ssh_username / node.ssh_password_enc)
  2. Primary group creds  (alphabetically-first group the node belongs to)
  3. Controller key       (node was bootstrapped — ssh_host_key set — and ~/.kri/id_rsa exists)
  4. Global default       (platform settings: SSH_USERNAME / SSH_PASSWORD)

Design intent: tiers 1 and 2 are explicit operator-set credentials and always
win.  Tier 3 applies only to nodes that have been bootstrapped (TOFU host-key
recorded) and have no explicit override; the controller private key was
installed on the node during bootstrap.  Tier 4 is the legacy password
fallback for nodes that have never been bootstrapped.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


def _read_controller_key() -> str:
    """Return the controller private key (~/.kri/id_rsa) or '' if absent/unreadable."""
    try:
        return _DEFAULT_PRIV.read_text()
    except OSError:
        return ""


async def resolve_node_credentials(node: Node, db: AsyncSession) -> dict:
    """Return resolved SSH credentials for a node.

    Returns dict with keys: ssh_user, ssh_password, ssh_key, auth_mode,
    credential_source ('node' | 'group:<name>' | 'global')
    """
    # 1. Node-level override
    if node.ssh_username:
        password = ""  # nosec B105 — default before decryption attempt, not a hardcoded credential
        if node.ssh_password_enc:
            try:
                password = decrypt_secret(node.ssh_password_enc)
            except Exception as exc:
                logger.warning(
                    "Fernet decryption failed for node %s field ssh_password: %s",
                    node.id,
                    exc,
                )
        ssh_key = ""
        if node.ssh_key_enc:
            try:
                ssh_key = decrypt_secret(node.ssh_key_enc)
            except Exception as exc:
                logger.warning(
                    "Fernet decryption failed for node %s field ssh_key: %s",
                    node.id,
                    exc,
                )
        return {
            "ssh_user": node.ssh_username,
            "ssh_password": password,
            "ssh_key": ssh_key,
            "auth_mode": node.ssh_auth_mode or "password",
            "credential_source": "node",
        }

    # 2. Primary group (alphabetically-first group that has credentials)
    result = await db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.node_id == node.id)
        .where(Group.ssh_username.isnot(None))
        .order_by(Group.name.asc())
        .limit(1)
    )
    group = result.scalar_one_or_none()
    if group and group.ssh_username:
        password = ""  # nosec B105 — default before decryption attempt, not a hardcoded credential
        if group.ssh_password_enc:
            try:
                password = decrypt_secret(group.ssh_password_enc)
            except Exception as exc:
                logger.warning(
                    "Fernet decryption failed for group %s field ssh_password (node %s): %s",
                    group.name,
                    node.id,
                    exc,
                )
        ssh_key = ""
        if group.ssh_key_enc:
            try:
                ssh_key = decrypt_secret(group.ssh_key_enc)
            except Exception as exc:
                logger.warning(
                    "Fernet decryption failed for group %s field ssh_key (node %s): %s",
                    group.name,
                    node.id,
                    exc,
                )
        return {
            "ssh_user": group.ssh_username,
            "ssh_password": password,
            "ssh_key": ssh_key,
            "auth_mode": group.ssh_auth_mode or "password",
            "credential_source": f"group:{group.name}",
        }

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


def _decrypt_or_blank(label: str, ident, field: str, ciphertext: str | None) -> str:
    if not ciphertext:
        return ""
    try:
        return decrypt_secret(ciphertext)
    except Exception as exc:
        logger.warning("Fernet decryption failed for %s %s field %s: %s", label, ident, field, exc)
        return ""


def resolve_node_credentials_sync(node: Node, db) -> dict:
    """Synchronous twin of :func:`resolve_node_credentials` for the Celery worker.

    The playbook worker runs on a sync SQLAlchemy ``Session`` (``get_sync_db``),
    so it cannot await the async resolver. This mirrors the same
    node → primary-group → controller → global priority chain and returns the
    identical dict shape, including ``credential_source`` (#279, #349).
    """
    # 1. Node-level override
    if node.ssh_username:
        return {
            "ssh_user": node.ssh_username,
            "ssh_password": _decrypt_or_blank("node", node.id, "ssh_password", node.ssh_password_enc),
            "ssh_key": _decrypt_or_blank("node", node.id, "ssh_key", node.ssh_key_enc),
            "auth_mode": node.ssh_auth_mode or "password",
            "credential_source": "node",
        }

    # 2. Primary group (alphabetically-first group that has credentials)
    group = db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.node_id == node.id)
        .where(Group.ssh_username.isnot(None))
        .order_by(Group.name.asc())
        .limit(1)
    ).scalar_one_or_none()
    if group and group.ssh_username:
        return {
            "ssh_user": group.ssh_username,
            "ssh_password": _decrypt_or_blank("group", group.name, "ssh_password", group.ssh_password_enc),
            "ssh_key": _decrypt_or_blank("group", group.name, "ssh_key", group.ssh_key_enc),
            "auth_mode": group.ssh_auth_mode or "password",
            "credential_source": f"group:{group.name}",
        }

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
