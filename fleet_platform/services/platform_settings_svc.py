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


def _fernet_key() -> bytes:
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_fernet_key())


async def get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(PlatformSetting).where(PlatformSetting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if row.is_encrypted and row.value:
        return _fernet().decrypt(row.value.encode()).decode()
    return row.value


async def get_playbooks_dir(db: AsyncSession) -> Path:
    """Return the configured playbooks directory, falling back to repo default."""
    custom = await get_setting(db, PLAYBOOKS_DIR)
    if custom:
        return Path(custom)
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
