# fleet_platform/api/routes/platform_settings.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.schemas.ansible import PlatformSettingsResponse, PlatformSettingsUpdate
from fleet_platform.services.platform_settings_svc import (
    SALT_MASTER, SSH_USERNAME, SSH_PASSWORD,
    get_setting, set_setting,
)
from fleet_platform.services.ssh_keypair import ensure_controller_keypair, get_controller_pubkey

router = APIRouter(prefix="/api/v1/settings")


@router.get("", response_model=PlatformSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    ensure_controller_keypair()
    return PlatformSettingsResponse(
        salt_master_address=await get_setting(db, SALT_MASTER),
        ssh_bootstrap_username=await get_setting(db, SSH_USERNAME),
        controller_pubkey=get_controller_pubkey(),
    )


@router.put("", response_model=PlatformSettingsResponse)
async def update_settings(
    payload: PlatformSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    ensure_controller_keypair()
    if payload.salt_master_address is not None:
        await set_setting(db, SALT_MASTER, payload.salt_master_address)
    if payload.ssh_bootstrap_username is not None:
        await set_setting(db, SSH_USERNAME, payload.ssh_bootstrap_username)
    if payload.ssh_bootstrap_password is not None:
        await set_setting(db, SSH_PASSWORD, payload.ssh_bootstrap_password, encrypt=True)
    return PlatformSettingsResponse(
        salt_master_address=await get_setting(db, SALT_MASTER),
        ssh_bootstrap_username=await get_setting(db, SSH_USERNAME),
        controller_pubkey=get_controller_pubkey(),
    )
