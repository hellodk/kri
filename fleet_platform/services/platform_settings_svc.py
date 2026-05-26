# fleet_platform/services/platform_settings_svc.py
import base64
import hashlib
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_REPO_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_PLAYBOOKS_DIR = _REPO_ROOT / "playbooks"

from fleet_platform.core.config import settings
from fleet_platform.models.platform_setting import PlatformSetting

# Setting key constants
SALT_MASTER = "salt_master_address"
SSH_USERNAME = "ssh_bootstrap_username"
SSH_PASSWORD = "ssh_bootstrap_password"
CONTROLLER_PRIVKEY_PATH = "controller_privkey_path"
CONTROLLER_PUBKEY_PATH = "controller_pubkey_path"
ANSIBLE_ENDPOINT_URL = "ansible_endpoint_url"
ANSIBLE_API_TOKEN = "ansible_api_token"
PLAYBOOKS_DIR = "playbooks_dir"
PILLAR_DIR = "pillar_dir"
KRI_API_URL = "kri_api_url"
CXONE_URL = "cxone_url"
CXONE_API_TOKEN = "cxone_api_token"
SONARQUBE_URL = "sonarqube_url"
SONARQUBE_TOKEN = "sonarqube_token"
LICENSE_POLICY = "license_policy"  # "permissive" | "strict"
VNC_ENABLED = "vnc_enabled"  # "true" | "false"


def _fernet_key() -> bytes:
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_fernet_key())


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret string for storage."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored secret."""
    return _fernet().decrypt(ciphertext.encode()).decode()


async def get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.is_encrypted and row.value:
        return _fernet().decrypt(row.value.encode()).decode()
    return row.value


async def get_playbooks_dir(db: AsyncSession) -> Path:
    """Return the configured playbooks directory, falling back to repo default.

    Applies PLAYBOOK_PATH_MAP translation so host-side paths resolve correctly
    inside Docker containers where volumes are mounted at different prefixes.
    """
    from fleet_platform.services.playbook_sources import _translate_path
    custom = await get_setting(db, PLAYBOOKS_DIR)
    if custom:
        return Path(_translate_path(custom))
    return _DEFAULT_PLAYBOOKS_DIR


async def set_setting(db: AsyncSession, key: str, value: str, encrypt: bool = False) -> None:
    stored_value = _fernet().encrypt(value.encode()).decode() if encrypt else value
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = stored_value
        row.is_encrypted = encrypt
    else:
        db.add(PlatformSetting(key=key, value=stored_value, is_encrypted=encrypt))
    await db.commit()


# Map from env-var name → (setting_key, is_encrypted)
# Only non-secret settings belong here — secrets must be set via the UI.
_ENV_DEFAULTS: list[tuple[str, str]] = [
    ("KRI_API_URL",          KRI_API_URL),
    ("SALT_MASTER_ADDRESS",  SALT_MASTER),
    ("PLAYBOOKS_DIR",        PLAYBOOKS_DIR),
    ("PILLAR_DIR",           PILLAR_DIR),
    ("SSH_BOOTSTRAP_USERNAME", SSH_USERNAME),
]


async def seed_settings_from_env(db: AsyncSession) -> None:
    """Upsert platform settings from environment variables if the DB row is absent.

    Called once at API startup.  Existing DB values always take priority — this
    only fills in rows that are completely missing (e.g. after a DB wipe).
    """
    import os
    for env_key, setting_key in _ENV_DEFAULTS:
        value = os.environ.get(env_key, "").strip()
        if not value:
            continue
        result = await db.execute(
            select(PlatformSetting).where(PlatformSetting.key == setting_key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            db.add(PlatformSetting(key=setting_key, value=value, is_encrypted=False))
    await db.commit()
