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
