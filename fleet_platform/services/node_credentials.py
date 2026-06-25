# fleet_platform/services/node_credentials.py
"""Credential-resolution helpers extracted from ansible_tasks (#750).

Resolve SSH credentials (per-node, per-group, and platform-bootstrap defaults)
and salt-api master credentials for grain collection. All decryption failures
are non-fatal and degrade to empty credentials with a warning.
"""

import logging
from pathlib import Path

from sqlalchemy import select

from fleet_platform.models.platform_setting import PlatformSetting
from fleet_platform.models.salt_master import SaltMaster
from fleet_platform.services.ssh_keypair import get_controller_pubkey

logger = logging.getLogger(__name__)

_DEFAULT_KRI_DIR = Path.home() / ".kri"


def _get_bootstrap_settings(db) -> tuple[str, str, str]:
    """Returns (ssh_user, ssh_password, controller_pubkey).

    The legacy salt_master address has been removed from this tuple (#562).
    Master addresses are resolved exclusively from SaltMaster rows.
    The SALT_MASTER platform setting key is still defined (migration 041 references it)
    but is no longer read at runtime.
    """
    from fleet_platform.services.platform_settings_svc import (
        CONTROLLER_PUBKEY_PATH,
        SSH_PASSWORD,
        SSH_USERNAME,
        _fernet,
    )

    def _get(key: str) -> str:
        row = db.execute(select(PlatformSetting).where(PlatformSetting.key == key)).scalar_one_or_none()
        if row is None:
            return ""
        if row.is_encrypted and row.value:
            try:
                return _fernet().decrypt(row.value.encode()).decode()
            except Exception:
                logger.warning(
                    "_get_bootstrap_settings: cannot decrypt setting '%s' — "
                    "JWT_SECRET may have changed. Re-enter credentials in Settings → Bootstrap.",
                    key,
                )
                return ""
        return row.value or ""

    ssh_user = _get(SSH_USERNAME) or "admin"
    ssh_password = _get(SSH_PASSWORD)
    pub_path = _get(CONTROLLER_PUBKEY_PATH) or str(_DEFAULT_KRI_DIR / "id_rsa.pub")
    pubkey = get_controller_pubkey(pub_path) or ""
    return ssh_user, ssh_password, pubkey


def _get_node_credentials(node) -> tuple[str, str, str]:
    """Returns (ssh_user, ssh_password, ssh_auth_mode) from per-node stored credentials."""
    from fleet_platform.services.platform_settings_svc import decrypt_secret

    user = node.ssh_username or ""
    password = ""
    auth_mode = node.ssh_auth_mode or "password"
    if node.ssh_password_enc:
        try:
            password = decrypt_secret(node.ssh_password_enc)
        except Exception as e:
            logger.warning(
                "_get_node_credentials: failed to decrypt ssh_password_enc"
                " for node_id=%s — using empty password. Cause: %s",
                node.id,
                e,
            )
    return user, password, auth_mode


def _get_group_credentials(node, db) -> tuple[str, str, str, str]:
    """Return (ssh_user, ssh_password, ssh_key, auth_mode) from node's primary group.

    Primary group = alphabetically-first group the node belongs to that has credentials.
    Returns empty strings for all fields if no group credentials exist.
    """
    from fleet_platform.models.group import Group, GroupMember
    from fleet_platform.services.platform_settings_svc import decrypt_secret

    result = db.execute(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.node_id == node.id)
        .where(Group.ssh_username.isnot(None))
        .order_by(Group.name.asc())
        .limit(1)
    )
    group = result.scalar_one_or_none()
    if not group:
        return "", "", "", ""

    password = ""
    if group.ssh_password_enc:
        try:
            password = decrypt_secret(group.ssh_password_enc)
        except Exception:
            logger.warning(
                "_get_group_credentials: cannot decrypt ssh_password for group %s node %s",
                group.name,
                node.id,
            )

    ssh_key = ""
    if group.ssh_key_enc:
        try:
            ssh_key = decrypt_secret(group.ssh_key_enc)
        except Exception:
            logger.warning(
                "_get_group_credentials: cannot decrypt ssh_key for group %s node %s",
                group.name,
                node.id,
            )

    logger.info(
        "bootstrap_node: using group '%s' credentials for node %s (auth_mode=%s)",
        group.name,
        node.id,
        group.ssh_auth_mode,
    )
    return group.ssh_username or "", password, ssh_key, group.ssh_auth_mode or "password"


def _resolve_node_master_creds(db, node) -> dict | None:
    """Resolve salt-api creds for the node's master (or the default master).

    Returns {api_url, api_user, api_password, api_eauth, tls_verify} or None
    when no enabled master is configured. Used by collect_node_grains to fetch
    grains over salt-api instead of SSH (#708).
    """
    from fleet_platform.services.platform_settings_svc import decrypt_secret

    master = None
    if node.salt_master_id is not None:
        master = db.execute(
            select(SaltMaster).where(SaltMaster.id == node.salt_master_id).where(SaltMaster.enabled.is_(True))
        ).scalar_one_or_none()
    if master is None:
        master = db.execute(
            select(SaltMaster).where(SaltMaster.is_default.is_(True)).where(SaltMaster.enabled.is_(True)).limit(1)
        ).scalar_one_or_none()
    if master is None:
        master = db.execute(select(SaltMaster).where(SaltMaster.enabled.is_(True)).limit(1)).scalar_one_or_none()
    if master is None:
        return None

    api_password = ""
    if master.api_password_enc:
        try:
            api_password = decrypt_secret(master.api_password_enc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("collect_node_grains: cannot decrypt api_password for master %s: %s", master.name, exc)
    return {
        "api_url": (master.api_url or "").rstrip("/"),
        "api_user": master.api_user or "",
        "api_password": api_password,
        "api_eauth": master.api_eauth or "pam",
        "tls_verify": bool(getattr(master, "tls_verify", False)),
    }
