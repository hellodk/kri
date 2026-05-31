"""Resolve effective SSH credentials for a node.

Priority chain (first match wins):
  1. Node-level override  (node.ssh_username / node.ssh_password_enc)
  2. Primary group creds  (alphabetically-first group the node belongs to)
  3. Global default       (platform settings: SSH_USERNAME / SSH_PASSWORD)
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

logger = logging.getLogger(__name__)


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

    # 3. Global fallback from platform settings
    ssh_user = await _get_global_setting(db, SSH_USERNAME) or "admin"
    ssh_password = await _get_global_setting(db, SSH_PASSWORD, encrypted=True)

    return {
        "ssh_user": ssh_user,
        "ssh_password": ssh_password,
        "ssh_key": "",
        "auth_mode": "password",
        "credential_source": "global",
    }


async def _get_global_setting(db: AsyncSession, key: str, encrypted: bool = False) -> str:
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == key)
    )
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
    result = await db.execute(
        select(GroupMember).where(GroupMember.node_id == node_id).limit(1)
    )
    return result.scalar_one_or_none() is not None
